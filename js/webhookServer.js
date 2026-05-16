const express = require('express');
const config = require('./config');
const { TokenStorage, handleOAuthCallback } = require('./googleAuth');
const { bot, setTokenStorage, handleDeletedMessage } = require('./bot');

const app = express();
app.use(express.json());

let tokenStorage;

app.get('/', (req, res) => {
  res.json({ status: 'ok', message: 'Telegram bot webhook server is running' });
});

app.get('/oauth/callback', async (req, res) => {
  const { code, state, error } = req.query;

  if (error) {
    console.warn(`OAuth error: ${error}`);
    return res.status(400).send(
      `<h1>Authentication Failed</h1><p>Error: ${error}</p><p>Please try /authenticate again in Telegram.</p>`
    );
  }

  if (!code || !state) {
    return res.status(400).send('<h1>Invalid Request</h1><p>Missing code or state parameter.</p>');
  }

  const userId = await handleOAuthCallback(
    code, state,
    config.googleClientId,
    config.googleClientSecret,
    config.googleRedirectUri,
    tokenStorage
  );

  if (!userId) {
    return res.status(400).send(
      '<h1>Authentication Failed</h1><p>Invalid or expired state. Please try /authenticate again in Telegram.</p>'
    );
  }

  try {
    await bot.sendMessage(userId,
      'Authentication successful! You can now send messages and they will be saved to your Google Drive.'
    );
  } catch (err) {
    console.error(`Failed to send confirmation to user ${userId}: ${err}`);
  }

  res.send('<h1>Authentication Successful!</h1><p>You can close this window and return to Telegram.</p>');
});

app.post(`${config.webhookPath}/${config.botToken}`, async (req, res) => {
  const update = req.body;
  try {
    if (update.deleted_messages) {
      const userIdFromChat = update.chat?.id;
      if (userIdFromChat) {
        for (const msg of update.deleted_messages) {
          if (msg.message_id) {
            await handleDeletedMessage(msg.message_id, userIdFromChat);
          }
        }
      }
    } else {
      bot.processUpdate(update);
    }
    res.sendStatus(200);
  } catch (err) {
    console.error(`Error processing update: ${err}`);
    res.sendStatus(500);
  }
});

async function setWebhook() {
  const webhookUrl = `${config.webhookUrl}${config.webhookPath}/${config.botToken}`;
  const redactedUrl = `${config.webhookUrl}${config.webhookPath}/[REDACTED]`;

  console.log(`Setting webhook URL: ${redactedUrl}`);
  try {
    await bot.setWebHook(webhookUrl, {
      allowed_updates: ['message', 'edited_message', 'message_delete'],
    });
    const info = await bot.getWebHookInfo();
    const loggedUrl = info.url ? info.url.replace(config.botToken, '[REDACTED]') : 'None';
    console.log(`Webhook set. URL: ${loggedUrl}, Pending updates: ${info.pending_update_count}`);
  } catch (err) {
    console.error(`Failed to set webhook: ${err}`);
    throw err;
  }
}

async function main() {
  console.log('Starting Telegram bot in webhook mode...');

  tokenStorage = new TokenStorage(config.databaseConfig, config.tokenEncryptionKey);
  setTokenStorage(tokenStorage);
  console.log('Token storage initialized');

  await setWebhook();

  app.listen(config.webhookPort, '0.0.0.0', () => {
    console.log(`Webhook server listening on port ${config.webhookPort}`);
  });
}

main().catch((err) => {
  console.error(`Failed to start: ${err}`);
  process.exit(1);
});
