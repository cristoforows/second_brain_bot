const { google } = require('googleapis');
const { Readable } = require('stream');
const { getCredentials } = require('./googleAuth');

const MARKDOWN_MIME_TYPE = 'text/markdown';

async function getDriveService(userId, tokenStorage, config) {
  const auth = await getCredentials(
    userId, tokenStorage,
    config.googleClientId, config.googleClientSecret, config.googleRedirectUri
  );
  if (!auth) return null;
  return google.drive({ version: 'v3', auth });
}

async function getOrCreateFolder(service, folderName) {
  try {
    const res = await service.files.list({
      q: `name='${folderName}' and mimeType='application/vnd.google-apps.folder' and trashed=false`,
      spaces: 'drive',
      fields: 'files(id)',
    });
    if (res.data.files.length) return res.data.files[0].id;

    const file = await service.files.create({
      requestBody: { name: folderName, mimeType: 'application/vnd.google-apps.folder' },
      fields: 'id',
    });
    console.log(`Created folder: ${folderName}`);
    return file.data.id;
  } catch (err) {
    console.error(`Failed to get/create folder: ${err}`);
    return null;
  }
}

function _getTargetDate(dayCutoffHour) {
  const now = new Date();
  if (dayCutoffHour > 0 && now.getHours() < dayCutoffHour) {
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    return yesterday;
  }
  return now;
}

function _formatDate(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

async function getOrCreateMarkdownFile(service, folderId, dayCutoffHour = 0) {
  const targetDate = _getTargetDate(dayCutoffHour);
  const fileName = `${_formatDate(targetDate)}.md`;

  try {
    const res = await service.files.list({
      q: `name='${fileName}' and mimeType='${MARKDOWN_MIME_TYPE}' and trashed=false and '${folderId}' in parents`,
      spaces: 'drive',
      fields: 'files(id)',
    });
    if (res.data.files.length) {
      console.log(`Found existing file: ${fileName}`);
      return res.data.files[0].id;
    }

    const file = await service.files.create({
      requestBody: {
        name: fileName,
        parents: [folderId],
        mimeType: MARKDOWN_MIME_TYPE,
      },
      media: {
        mimeType: MARKDOWN_MIME_TYPE,
        body: '# Telegram Messages\n\n',
      },
      fields: 'id',
    });
    console.log(`Created new file: ${fileName}`);
    return file.data.id;
  } catch (err) {
    console.error(`Failed to get/create markdown file: ${err}`);
    return null;
  }
}

async function appendMessage(service, fileId, messageId, content) {
  try {
    const current = await _downloadFile(service, fileId);
    if (current === null) return false;
    const block = `<!-- msg_id: ${messageId} -->\n${content}\n`;
    return _uploadFile(service, fileId, current + block);
  } catch (err) {
    console.error(`Failed to append message ${messageId}: ${err}`);
    return false;
  }
}

async function updateMessage(service, fileId, messageId, newContent) {
  try {
    const current = await _downloadFile(service, fileId);
    if (current === null) return false;
    const updated = _replaceBlock(current, messageId, newContent);
    if (updated === null) return false;
    return _uploadFile(service, fileId, updated);
  } catch (err) {
    console.error(`Failed to update message ${messageId}: ${err}`);
    return false;
  }
}

async function deleteMessage(service, fileId, messageId) {
  try {
    const current = await _downloadFile(service, fileId);
    if (current === null) return false;
    const updated = _removeBlock(current, messageId);
    if (updated === null) return true; // Not found — silently succeed
    return _uploadFile(service, fileId, updated);
  } catch (err) {
    console.error(`Failed to delete message ${messageId}: ${err}`);
    return false;
  }
}

function _replaceBlock(content, messageId, newContent) {
  const headerRe = new RegExp(`<!-- msg_id: ${messageId} -->\\n`);
  const match = headerRe.exec(content);
  if (!match) return null;

  const blockStart = match.index;
  const headerEnd = match.index + match[0].length;
  const nextRe = /<!-- msg_id: \d+ -->\n/g;
  nextRe.lastIndex = headerEnd;
  const nextMatch = nextRe.exec(content);
  const blockEnd = nextMatch ? nextMatch.index : content.length;

  return content.slice(0, blockStart) + `<!-- msg_id: ${messageId} -->\n${newContent}\n` + content.slice(blockEnd);
}

function _removeBlock(content, messageId) {
  const headerRe = new RegExp(`<!-- msg_id: ${messageId} -->\\n`);
  const match = headerRe.exec(content);
  if (!match) return null;

  const blockStart = match.index;
  const headerEnd = match.index + match[0].length;
  const nextRe = /<!-- msg_id: \d+ -->\n/g;
  nextRe.lastIndex = headerEnd;
  const nextMatch = nextRe.exec(content);
  const blockEnd = nextMatch ? nextMatch.index : content.length;

  return content.slice(0, blockStart) + content.slice(blockEnd);
}

async function _downloadFile(service, fileId) {
  try {
    const res = await service.files.get({ fileId, alt: 'media' }, { responseType: 'text' });
    return typeof res.data === 'string' ? res.data : String(res.data);
  } catch (err) {
    console.error(`Failed to download file ${fileId}: ${err}`);
    return null;
  }
}

async function _uploadFile(service, fileId, content) {
  try {
    await service.files.update({
      fileId,
      media: {
        mimeType: MARKDOWN_MIME_TYPE,
        body: Readable.from([content]),
      },
    });
    return true;
  } catch (err) {
    console.error(`Failed to upload file ${fileId}: ${err}`);
    return false;
  }
}

module.exports = {
  getDriveService,
  getOrCreateFolder,
  getOrCreateMarkdownFile,
  appendMessage,
  updateMessage,
  deleteMessage,
};
