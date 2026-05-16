require('dotenv').config();

class Config {
  constructor() {
    this.botToken = this._getBotToken();
    this.logLevel = (process.env.LOG_LEVEL || 'info').toLowerCase();
    this.webhookUrl = (process.env.WEBHOOK_URL || '').replace(/\/$/, '');
    this.webhookPort = this._getWebhookPort();
    this.webhookPath = this._getWebhookPath();

    this.googleClientId = this._require('GOOGLE_CLIENT_ID');
    this.googleClientSecret = process.env.GOOGLE_CLIENT_SECRET || '';
    this.googleRedirectUri = process.env.GOOGLE_REDIRECT_URI || `${this.webhookUrl}/oauth/callback`;

    this.databaseConfig = this._getDatabaseConfig();
    this.tokenEncryptionKey = this._require('TOKEN_ENCRYPTION_KEY');

    this.driveFolderName = process.env.DRIVE_FOLDER_NAME || 'second_brain_bot/';
    this.dayCutoffHour = this._getDayCutoffHour();
  }

  _getBotToken() {
    const token = process.env.TELEGRAM_BOT_TOKEN;
    if (!token) {
      console.error('TELEGRAM_BOT_TOKEN not found in environment variables');
      process.exit(1);
    }
    const parts = token.split(':');
    if (parts.length !== 2 || !/^\d+$/.test(parts[0]) || parts[1].length < 20) {
      console.error('Invalid bot token format');
      process.exit(1);
    }
    return token;
  }

  _require(name) {
    const val = process.env[name];
    if (!val) {
      console.error(`${name} not found in environment`);
      process.exit(1);
    }
    return val;
  }

  _getWebhookPort() {
    const port = parseInt(process.env.WEBHOOK_PORT || '8443', 10);
    if (![80, 88, 443, 8443].includes(port)) {
      console.warn(`Port ${port} not in Telegram allowed ports (80, 88, 443, 8443), using 8443`);
      return 8443;
    }
    return port;
  }

  _getWebhookPath() {
    const path = process.env.WEBHOOK_PATH || '/webhook';
    return path.startsWith('/') ? path : `/${path}`;
  }

  _getDatabaseConfig() {
    return {
      user: process.env.DATABASE_USER,
      password: process.env.DATABASE_PASSWORD,
      host: process.env.DATABASE_HOST,
      port: parseInt(process.env.DATABASE_PORT || '5432', 10),
      database: process.env.DATABASE_NAME,
    };
  }

  _getDayCutoffHour() {
    const raw = process.env.DAY_CUTOFF_HOUR || '0';
    const hour = parseInt(raw, 10);
    if (isNaN(hour)) {
      console.warn(`Invalid DAY_CUTOFF_HOUR=${raw}, using 0`);
      return 0;
    }
    if (hour < 0 || hour > 23) {
      console.warn(`DAY_CUTOFF_HOUR=${hour} out of range (0-23), using 0`);
      return 0;
    }
    return hour;
  }
}

module.exports = new Config();
