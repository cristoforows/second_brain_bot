const TelegramBot = require('node-telegram-bot-api');
const config = require('./config');
const { generateAuthUrl } = require('./googleAuth');
const driveHandler = require('./driveHandler');

// Create bot in webhook mode (no polling)
const bot = new TelegramBot(config.botToken);

// Set by webhookServer.js before updates start flowing
let tokenStorage = null;

function setTokenStorage(storage) {
  tokenStorage = storage;
}

bot.onText(/\/start/, async (msg) => {
  const chatId = msg.chat.id;
  const userId = msg.from.id;
  try {
    const isAuthed = tokenStorage && await tokenStorage.isAuthenticated(userId);
    const text = isAuthed
      ? 'Welcome back to Second Brain Bot!\n\nYou are authenticated with Google Drive.\nSend me any message and I\'ll save it to your Drive.\n\nCommands:\n/status - Check connection status\n/logout - Disconnect Google Drive\n/help - Show help'
      : 'Welcome to Second Brain Bot!\n\nI save your Telegram messages to Google Drive as markdown files.\n\nTo get started, authenticate with Google Drive:\n/authenticate - Connect your Google Drive\n\n/help - Show help';
    await bot.sendMessage(chatId, text);
    console.log(`Sent welcome message to user ${userId}`);
  } catch (err) {
    console.error(`Error in /start for user ${userId}: ${err}`);
    await bot.sendMessage(chatId, 'Sorry, something went wrong. Please try again.');
  }
});

bot.onText(/\/help/, async (msg) => {
  const chatId = msg.chat.id;
  try {
    await bot.sendMessage(chatId,
      'Second Brain Bot Help\n\n' +
      'What I do:\nI save your Telegram messages to a markdown file in your Google Drive. Edit a message here and it updates in Drive too.\n\n' +
      'Commands:\n/authenticate - Connect your Google Drive\n/status - Check connection status\n/logout - Disconnect Google Drive\n/help - Show this help message\n\n' +
      'How to use:\n1. Use /authenticate to connect Google Drive\n2. Send me any text message\n3. It gets saved to your Drive as markdown\n4. Edit a message and Drive updates automatically'
    );
    console.log(`Sent help message to user ${msg.from.id}`);
  } catch (err) {
    console.error(`Error in /help: ${err}`);
  }
});

bot.onText(/\/authenticate/, async (msg) => {
  const chatId = msg.chat.id;
  const userId = msg.from.id;

  if (!tokenStorage) {
    await bot.sendMessage(chatId, 'Bot is not configured properly. Please contact the administrator.');
    return;
  }

  try {
    if (await tokenStorage.isAuthenticated(userId)) {
      await bot.sendMessage(chatId,
        'You are already authenticated with Google Drive.\nUse /status to check your connection or /logout to disconnect.'
      );
      return;
    }

    const authUrl = generateAuthUrl(
      userId,
      config.googleClientId,
      config.googleClientSecret,
      config.googleRedirectUri
    );
    await bot.sendMessage(chatId,
      `Authenticate with Google Drive\n\nClick the link below to authorize:\n${authUrl}\n\nThe link expires in 10 minutes.`
    );
    console.log(`Sent OAuth URL to user ${userId}`);
  } catch (err) {
    console.error(`Error in /authenticate for user ${userId}: ${err}`);
    await bot.sendMessage(chatId, 'Failed to generate authentication link. Please try again.');
  }
});

bot.onText(/\/status/, async (msg) => {
  const chatId = msg.chat.id;
  const userId = msg.from.id;

  try {
    if (!tokenStorage || !await tokenStorage.isAuthenticated(userId)) {
      await bot.sendMessage(chatId, 'Not Authenticated\n\nUse /authenticate to connect your Google Drive.');
      return;
    }

    const tokenData = await tokenStorage.getUserToken(userId);
    let expiryInfo = 'Unknown';
    if (tokenData && tokenData.expiry_date) {
      const remaining = tokenData.expiry_date - Date.now();
      const hours = Math.floor(remaining / 3_600_000);
      expiryInfo = hours > 0 ? `${hours} hours` : 'Token will auto-refresh';
    }

    await bot.sendMessage(chatId,
      `Authentication Status\n\nGoogle Drive: Connected\nToken expires in: ${expiryInfo}\nFolder: ${config.driveFolderName}\n\nSend any message to save to Drive!`
    );
  } catch (err) {
    console.error(`Error in /status for user ${userId}: ${err}`);
    await bot.sendMessage(chatId, 'Sorry, something went wrong. Please try again.');
  }
});

bot.onText(/\/logout/, async (msg) => {
  const chatId = msg.chat.id;
  const userId = msg.from.id;

  try {
    if (!tokenStorage || !await tokenStorage.isAuthenticated(userId)) {
      await bot.sendMessage(chatId, 'You are not currently authenticated.');
      return;
    }

    await tokenStorage.deleteUserToken(userId);
    await bot.sendMessage(chatId,
      'Logged out successfully.\n\nYour authentication has been removed.\nUse /authenticate to connect again.'
    );
    console.log(`User ${userId} logged out`);
  } catch (err) {
    console.error(`Error in /logout for user ${userId}: ${err}`);
    await bot.sendMessage(chatId, 'Failed to log out. Please try again.');
  }
});

// Non-command text messages
bot.on('message', async (msg) => {
  if (!msg.text || msg.text.startsWith('/')) return;

  const chatId = msg.chat.id;
  const userId = msg.from.id;

  if (!tokenStorage || !await tokenStorage.isAuthenticated(userId)) {
    await bot.sendMessage(chatId, 'Please authenticate with Google Drive first using /authenticate');
    return;
  }

  await _storeMessage(msg, false);
});

// Edited message handler
bot.on('edited_message', async (msg) => {
  if (!msg.text) return;
  await _storeMessage(msg, true);
});

async function _storeMessage(msg, isEdited) {
  const chatId = msg.chat.id;
  const userId = msg.from.id;
  const messageId = msg.message_id;
  const text = msg.text || '';

  try {
    const service = await driveHandler.getDriveService(userId, tokenStorage, config);
    if (!service) {
      await bot.sendMessage(chatId,
        'Your Google Drive session has expired and could not be refreshed. ' +
        'Your message was not saved. Please use /logout then /authenticate to reconnect.'
      );
      return;
    }

    const folderId = await driveHandler.getOrCreateFolder(service, config.driveFolderName);
    if (!folderId) {
      await bot.sendMessage(chatId,
        'Could not find or create the folder in Google Drive. Your message was not saved. Please try again later.'
      );
      return;
    }

    const fileId = await driveHandler.getOrCreateMarkdownFile(service, folderId, config.dayCutoffHour);
    if (!fileId) {
      await bot.sendMessage(chatId,
        'Could not find or create the markdown file in Google Drive. Your message was not saved. Please try again later.'
      );
      return;
    }

    let success;
    if (isEdited) {
      success = await driveHandler.updateMessage(service, fileId, messageId, text);
      if (!success) {
        // Message not found for edit — append as new
        success = await driveHandler.appendMessage(service, fileId, messageId, text);
        if (success) console.log(`Edited message ${messageId} appended as new for user ${userId}`);
      } else {
        console.log(`Message ${messageId} updated in Drive for user ${userId}`);
      }
    } else {
      success = await driveHandler.appendMessage(service, fileId, messageId, text);
      if (success) console.log(`Message ${messageId} saved to Drive for user ${userId}`);
    }

    if (!success) {
      await bot.sendMessage(chatId,
        isEdited
          ? 'Failed to update your edited message in Google Drive. The change was not saved. Please try again.'
          : 'Failed to save your message to Google Drive. Your message was not saved. Please try again.'
      );
    }
  } catch (err) {
    console.error(`Error saving message for user ${userId}: ${err}`);
    await bot.sendMessage(chatId,
      'An unexpected error occurred while saving to Google Drive. Your message was not saved. Please try again later.'
    );
  }
}

async function handleDeletedMessage(messageId, userId) {
  if (!tokenStorage || !await tokenStorage.isAuthenticated(userId)) return;

  try {
    const service = await driveHandler.getDriveService(userId, tokenStorage, config);
    if (!service) return;

    const folderId = await driveHandler.getOrCreateFolder(service, config.driveFolderName);
    if (!folderId) return;

    const fileId = await driveHandler.getOrCreateMarkdownFile(service, folderId, config.dayCutoffHour);
    if (!fileId) return;

    await driveHandler.deleteMessage(service, fileId, messageId);
    console.log(`Deleted message ${messageId} from Drive for user ${userId}`);
  } catch (err) {
    console.error(`Error deleting message ${messageId} for user ${userId}: ${err}`);
  }
}

module.exports = { bot, setTokenStorage, handleDeletedMessage };
