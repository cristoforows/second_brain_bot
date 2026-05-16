const { google } = require('googleapis');
const { Pool } = require('pg');
const crypto = require('crypto');

const SCOPES = ['https://www.googleapis.com/auth/drive.file'];
const STATE_TTL_MS = 10 * 60 * 1000; // 10 minutes

// In-memory state cache for CSRF protection
// Maps state -> { userId, expires }
const stateCache = new Map();

class TokenStorage {
  constructor(databaseConfig, encryptionKey) {
    this.pool = new Pool(databaseConfig);
    // Derive a 32-byte AES key from the provided string
    this._key = crypto.createHash('sha256').update(String(encryptionKey)).digest();
  }

  _encrypt(text) {
    const iv = crypto.randomBytes(12);
    const cipher = crypto.createCipheriv('aes-256-gcm', this._key, iv);
    const encrypted = Buffer.concat([cipher.update(text, 'utf8'), cipher.final()]);
    const authTag = cipher.getAuthTag();
    // Format: iv(12 bytes) + authTag(16 bytes) + ciphertext
    return Buffer.concat([iv, authTag, encrypted]).toString('base64');
  }

  _decrypt(encryptedData) {
    const buf = Buffer.from(encryptedData, 'base64');
    const iv = buf.subarray(0, 12);
    const authTag = buf.subarray(12, 28);
    const encrypted = buf.subarray(28);
    const decipher = crypto.createDecipheriv('aes-256-gcm', this._key, iv);
    decipher.setAuthTag(authTag);
    return Buffer.concat([decipher.update(encrypted), decipher.final()]).toString('utf8');
  }

  async saveUserToken(userId, tokenData) {
    const encrypted = this._encrypt(JSON.stringify(tokenData));
    const expiresAt = tokenData.expiry_date ? new Date(tokenData.expiry_date) : null;
    await this.pool.query(
      `INSERT INTO user_tokens (user_id, encrypted_token, token_expires_at, last_accessed)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (user_id) DO UPDATE SET
         encrypted_token = EXCLUDED.encrypted_token,
         token_expires_at = EXCLUDED.token_expires_at,
         last_accessed = EXCLUDED.last_accessed`,
      [userId, encrypted, expiresAt, new Date()]
    );
    console.log(`Token saved for user ${userId}`);
  }

  async getUserToken(userId) {
    const result = await this.pool.query(
      'SELECT encrypted_token FROM user_tokens WHERE user_id = $1',
      [userId]
    );
    if (!result.rows.length) return null;
    const tokenData = JSON.parse(this._decrypt(result.rows[0].encrypted_token));
    await this.pool.query(
      'UPDATE user_tokens SET last_accessed = $1 WHERE user_id = $2',
      [new Date(), userId]
    );
    return tokenData;
  }

  async deleteUserToken(userId) {
    await this.pool.query('DELETE FROM user_tokens WHERE user_id = $1', [userId]);
    console.log(`Token deleted for user ${userId}`);
  }

  async isAuthenticated(userId) {
    const result = await this.pool.query(
      'SELECT 1 FROM user_tokens WHERE user_id = $1 LIMIT 1',
      [userId]
    );
    return result.rows.length > 0;
  }
}

function _makeOAuth2Client(clientId, clientSecret, redirectUri) {
  return new google.auth.OAuth2(clientId, clientSecret, redirectUri);
}

function generateAuthUrl(userId, clientId, clientSecret, redirectUri) {
  const client = _makeOAuth2Client(clientId, clientSecret, redirectUri);
  const state = crypto.randomBytes(32).toString('hex');
  stateCache.set(state, { userId, expires: Date.now() + STATE_TTL_MS });

  const url = client.generateAuthUrl({
    access_type: 'offline',
    scope: SCOPES,
    state,
    prompt: 'consent',
  });

  console.log(`Generated OAuth URL for user ${userId}`);
  return url;
}

async function handleOAuthCallback(code, state, clientId, clientSecret, redirectUri, tokenStorage) {
  const stateData = stateCache.get(state);
  if (!stateData || Date.now() > stateData.expires) {
    stateCache.delete(state);
    console.warn('OAuth callback with invalid or expired state');
    return null;
  }
  stateCache.delete(state);

  const { userId } = stateData;
  const client = _makeOAuth2Client(clientId, clientSecret, redirectUri);

  let tokens;
  try {
    const result = await client.getToken(code);
    tokens = result.tokens;
  } catch (err) {
    console.error(`Failed to exchange OAuth code for user ${userId}: ${err}`);
    return null;
  }

  await tokenStorage.saveUserToken(userId, tokens);
  console.log(`OAuth completed successfully for user ${userId}`);
  return userId;
}

async function getCredentials(userId, tokenStorage, clientId, clientSecret, redirectUri) {
  const tokenData = await tokenStorage.getUserToken(userId);
  if (!tokenData) return null;

  const client = _makeOAuth2Client(clientId, clientSecret, redirectUri);
  client.setCredentials(tokenData);

  // Auto-refresh if expired (with 60s buffer)
  if (tokenData.expiry_date && Date.now() >= tokenData.expiry_date - 60_000) {
    try {
      const { credentials } = await client.refreshAccessToken();
      client.setCredentials(credentials);
      await tokenStorage.saveUserToken(userId, credentials);
      console.log(`Token refreshed for user ${userId}`);
    } catch (err) {
      console.error(`Token refresh failed for user ${userId}: ${err}`);
      await tokenStorage.deleteUserToken(userId);
      return null;
    }
  }

  return client;
}

module.exports = { TokenStorage, generateAuthUrl, handleOAuthCallback, getCredentials };
