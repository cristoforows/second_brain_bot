"""
Configuration management for Telegram Echo Bot.
Handles environment variables, token validation, and logging setup.
"""

import os
import logging
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Configuration class for the Telegram bot."""

    def __init__(self):
        """Initialize configuration with validation."""
        self.bot_token = self._get_bot_token()
        self.log_level = self._get_log_level()
        self.webhook_url = self._get_webhook_url()
        self.webhook_port = self._get_webhook_port()
        self.webhook_path = self._get_webhook_path()

        # Google OAuth configuration
        self.google_client_id = self._get_google_client_id()
        self.google_client_secret = self._get_google_client_secret()
        self.google_redirect_uri = self._get_google_redirect_uri()

        # Database configuration
        self.database_url = self._get_database_params()
        self.token_encryption_key = self._get_token_encryption_key()

        # Google Drive settings
        self.drive_folder_name = self._get_drive_folder_name()
        self.day_cutoff_hour = self._get_day_cutoff_hour()

        self._setup_logging()

    def _get_bot_token(self) -> str:
        """Get and validate the Telegram bot token."""
        token = os.getenv('TELEGRAM_BOT_TOKEN')

        if not token:
            logging.error("TELEGRAM_BOT_TOKEN not found in environment variables")
            logging.error("Please create a .env file with your bot token")
            logging.error("You can get a bot token from @BotFather on Telegram")
            sys.exit(1)

        # Basic token validation
        if not self._is_valid_token_format(token):
            logging.error("Invalid bot token format")
            logging.error("Token should be in format: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
            sys.exit(1)

        return token

    def _is_valid_token_format(self, token: str) -> bool:
        """Validate basic token format."""
        parts = token.split(':')
        if len(parts) != 2:
            return False

        # Check if first part is numeric (bot ID)
        try:
            int(parts[0])
        except ValueError:
            return False

        # Check if second part exists and has reasonable length
        if len(parts[1]) < 20:
            return False

        return True

    def _get_log_level(self) -> str:
        """Get logging level from environment variables."""
        level = os.getenv('LOG_LEVEL', 'INFO').upper()

        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if level not in valid_levels:
            level = 'INFO'

        return level

    def _get_webhook_url(self) -> str:
        """Get webhook URL from environment variables."""
        url = os.getenv('WEBHOOK_URL', '')
        if not url:
            logging.warning("WEBHOOK_URL not set, webhook mode may not work")
        return url.rstrip('/')

    def _get_webhook_port(self) -> int:
        """Get webhook port from environment variables."""
        port = os.getenv('WEBHOOK_PORT', '8443')
        try:
            port_int = int(port)
            # Telegram only allows specific ports
            if port_int not in [80, 88, 443, 8443]:
                logging.warning(f"Port {port_int} not in Telegram allowed ports (80, 88, 443, 8443), using 8443")
                return 8443
            return port_int
        except ValueError:
            logging.warning(f"Invalid port {port}, using default 8443")
            return 8443

    def _get_webhook_path(self) -> str:
        """Get webhook path from environment variables."""
        path = os.getenv('WEBHOOK_PATH', '/webhook')
        return path if path.startswith('/') else f'/{path}'

    def _get_google_client_id(self) -> str:
        """Get Google OAuth client ID."""
        client_id = os.getenv('GOOGLE_CLIENT_ID')
        if not client_id:
            logging.error("GOOGLE_CLIENT_ID not found in .env")
            sys.exit(1)
        return client_id

    def _get_google_client_secret(self) -> str:
        """Get Google OAuth client secret."""
        return os.getenv('GOOGLE_CLIENT_SECRET', '')

    def _get_google_redirect_uri(self) -> str:
        """Get OAuth redirect URI."""
        return os.getenv('GOOGLE_REDIRECT_URI', f"{self.webhook_url}/oauth/callback")

    def _get_database_params(self) -> dict[str, str]:
        """Get PostgreSQL database URL (direct connection)."""
        db_username = os.getenv('DATABASE_USER')
        db_password = os.getenv('DATABASE_PASSWORD')
        db_host = os.getenv('DATABASE_HOST')
        db_port = os.getenv('DATABASE_PORT')
        db_name = os.getenv('DATABASE_NAME')
        return {
            "username": db_username,
            "password": db_password,
            "host": db_host,
            "port": db_port,
            "database": db_name
        }

    def _get_token_encryption_key(self) -> str:
        """Get token encryption key for Fernet."""
        key = os.getenv('TOKEN_ENCRYPTION_KEY')
        if not key:
            logging.error("TOKEN_ENCRYPTION_KEY not found. Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
            sys.exit(1)
        return key

    def _get_drive_folder_name(self) -> str:
        """Get Drive markdown file name."""
        return os.getenv('DRIVE_FOLDER_NAME', 'second_brain_bot/')

    def _get_day_cutoff_hour(self) -> int:
        """Get the hour (0-23) before which messages belong to the previous day's file.

        For example, DAY_CUTOFF_HOUR=4 means messages sent between 00:00 and 03:59
        are appended to the previous day's file. Defaults to 0 (no cutoff — midnight).
        """
        raw = os.getenv('DAY_CUTOFF_HOUR', '0')
        try:
            hour = int(raw)
            if not 0 <= hour <= 23:
                logging.warning(f"DAY_CUTOFF_HOUR={hour} out of range (0-23), using 0")
                return 0
            return hour
        except ValueError:
            logging.warning(f"Invalid DAY_CUTOFF_HOUR={raw!r}, using 0")
            return 0

    def _setup_logging(self):
        """Configure logging for the application."""
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=getattr(logging, self.log_level),
            handlers=[
                logging.StreamHandler(sys.stdout)
            ]
        )

        # Set specific logging levels for telegram libraries
        logging.getLogger('httpx').setLevel(logging.WARNING)
        logging.getLogger('telegram').setLevel(logging.INFO)


# Create global config instance
config = Config()