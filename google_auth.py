"""
Google OAuth 2.0 authentication and token storage.
Handles OAuth flow, encrypted token storage in PostgreSQL, and token refresh.
"""

import logging
import json
import secrets
import time
from datetime import datetime

import psycopg2
from psycopg2 import pool
from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/drive.file']

# In-memory state cache for CSRF protection during OAuth flow
# Maps state string -> {"user_id": int, "expires": float}
_state_cache: dict[str, dict] = {}


class TokenStorage:
    """Encrypted token storage using PostgreSQL (Supabase) and Fernet encryption."""

    def __init__(self, database_url: dict, encryption_key: str):
        """Initialize token storage with direct PostgreSQL connection pooling."""
        logger.warning(f"Database URL: {database_url}")
        self.connection_pool = psycopg2.pool.SimpleConnectionPool(1, 10,
            user=database_url['username'],
            password=database_url['password'],
            host=database_url['host'],
            port=database_url['port'],
            database=database_url['database'])
        self.fernet = Fernet(encryption_key.encode())
        logger.info("TokenStorage initialized with PostgreSQL connection pool")

    def save_user_token(self, user_id: int, token_data: dict) -> None:
        """Save encrypted token to PostgreSQL database."""
        token_json = json.dumps(token_data)
        encrypted_token = self.fernet.encrypt(token_json.encode()).decode()

        expires_at = None
        if token_data.get('expiry'):
            try:
                expires_at = datetime.fromisoformat(token_data['expiry'])
            except (ValueError, TypeError):
                pass

        conn = self.connection_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO user_tokens (user_id, encrypted_token, token_expires_at, last_accessed)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id)
                    DO UPDATE SET
                        encrypted_token = EXCLUDED.encrypted_token,
                        token_expires_at = EXCLUDED.token_expires_at,
                        last_accessed = EXCLUDED.last_accessed
                """, (user_id, encrypted_token, expires_at, datetime.now()))
                conn.commit()
            logger.info(f"Token saved for user {user_id}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to save token for user {user_id}: {e}")
            raise
        finally:
            self.connection_pool.putconn(conn)

    def get_user_token(self, user_id: int) -> dict | None:
        """Load and decrypt token from PostgreSQL database."""
        conn = self.connection_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT encrypted_token FROM user_tokens WHERE user_id = %s",
                    (user_id,)
                )
                row = cur.fetchone()

                if not row:
                    return None

                encrypted_token = row[0]
                decrypted_data = self.fernet.decrypt(encrypted_token.encode())
                token_data = json.loads(decrypted_data.decode())

                cur.execute(
                    "UPDATE user_tokens SET last_accessed = %s WHERE user_id = %s",
                    (datetime.now(), user_id)
                )
                conn.commit()

                return token_data
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to get token for user {user_id}: {e}")
            return None
        finally:
            self.connection_pool.putconn(conn)

    def delete_user_token(self, user_id: int) -> None:
        """Delete token from PostgreSQL database."""
        conn = self.connection_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM user_tokens WHERE user_id = %s", (user_id,))
                conn.commit()
            logger.info(f"Token deleted for user {user_id}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete token for user {user_id}: {e}")
            raise
        finally:
            self.connection_pool.putconn(conn)

    def is_authenticated(self, user_id: int) -> bool:
        """Check if user has a stored token."""
        conn = self.connection_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM user_tokens WHERE user_id = %s LIMIT 1",
                    (user_id,)
                )
                return cur.fetchone() is not None
        finally:
            self.connection_pool.putconn(conn)


def _credentials_to_dict(credentials: Credentials) -> dict:
    """Convert Google Credentials object to a serializable dict."""
    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': list(credentials.scopes) if credentials.scopes else SCOPES,
        'expiry': credentials.expiry.isoformat() if credentials.expiry else None,
    }


def generate_auth_url(user_id: int, client_id: str, client_secret: str, redirect_uri: str) -> str:
    """Generate an OAuth authorization URL for the user.

    Returns the URL the user should visit to grant permissions.
    """
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )

    state = _generate_state(user_id)

    authorization_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
        state=state,
    )

    logger.info(f"Generated OAuth URL for user {user_id}")
    return authorization_url


def handle_oauth_callback(
    code: str,
    state: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    token_storage: TokenStorage,
) -> int | None:
    """Handle the OAuth callback: validate state, exchange code for tokens, save.

    Returns the user_id on success, None on failure.
    """
    user_id = _validate_state(state)
    if user_id is None:
        logger.warning("OAuth callback with invalid or expired state")
        return None

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )

    try:
        flow.fetch_token(code=code)
    except Exception as e:
        logger.error(f"Failed to exchange OAuth code for user {user_id}: {e}")
        return None

    credentials = flow.credentials
    token_data = _credentials_to_dict(credentials)
    token_storage.save_user_token(user_id, token_data)

    logger.info(f"OAuth completed successfully for user {user_id}")
    return user_id


def get_credentials(user_id: int, token_storage: TokenStorage) -> Credentials | None:
    """Load user credentials, refreshing if expired.

    Returns valid Credentials or None if user must re-authenticate.
    """
    token_data = token_storage.get_user_token(user_id)
    if not token_data:
        return None

    credentials = Credentials(
        token=token_data['token'],
        refresh_token=token_data.get('refresh_token'),
        token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
        client_id=token_data.get('client_id'),
        client_secret=token_data.get('client_secret'),
        scopes=token_data.get('scopes', SCOPES),
    )

    if credentials.expiry:
        credentials.expiry = datetime.fromisoformat(token_data['expiry'])

    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            token_storage.save_user_token(user_id, _credentials_to_dict(credentials))
            logger.info(f"Token refreshed for user {user_id}")
        except RefreshError:
            logger.warning(f"Token refresh failed for user {user_id}, must re-authenticate")
            token_storage.delete_user_token(user_id)
            return None

    return credentials


# --- State management (CSRF protection) ---

def _generate_state(user_id: int) -> str:
    """Generate a state parameter with user_id and random nonce."""
    nonce = secrets.token_urlsafe(16)
    state = f"{user_id}:{nonce}"
    _state_cache[state] = {"user_id": user_id, "expires": time.time() + 600}
    return state


def _validate_state(state: str) -> int | None:
    """Validate state and return user_id. One-time use."""
    if state not in _state_cache:
        return None

    data = _state_cache.pop(state)

    if time.time() > data["expires"]:
        return None

    return data["user_id"]
