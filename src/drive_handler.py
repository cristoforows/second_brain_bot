"""
Google Drive handler for creating and managing markdown files.
Handles file creation, message appending, and message editing in Drive.
"""

import logging
import re
from datetime import datetime

from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

from google_auth import get_credentials, TokenStorage

logger = logging.getLogger(__name__)

MARKDOWN_MIME_TYPE = 'text/markdown'

# Regex to match comment-style message blocks
# <!-- msg_id: 12345 | from: @username | date: 2024-02-10 14:30:00 -->
MESSAGE_PATTERN = re.compile(
    r'<!-- msg_id: (\d+) -->\n'
)


def get_drive_service(user_id: int, token_storage: TokenStorage):
    """Get an authenticated Google Drive API service for a user."""
    credentials = get_credentials(user_id, token_storage)
    if not credentials:
        return None
    return build('drive', 'v3', credentials=credentials)

def get_or_create_folder(service, folder_name: str) -> str | None:
    """Find existing folder or create a new one in Drive.
    """
    try:
        results = service.files().list(
            q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            spaces='drive',
            fields='files(id, name)',
        ).execute()
        folders = results.get('files', [])
        if folders:
            folder_id = folders[0]['id']
            logger.info(f"Found existing folder: {folder_name} (ID: {folder_id})")
            return folder_id

        # Create new folder
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
        }
        folder = service.files().create(
            body=file_metadata,
            fields='id',
        ).execute()
        folder_id = folder.get('id')
        logger.info(f"Created new folder: {folder_name} (ID: {folder_id})")
        return folder_id
    except Exception as e:
        logger.error(f"Failed to get/create folder: {e}")
        return None

def get_or_create_markdown_file(service, folder_id: str) -> str | None:
    """Find existing markdown file or create a new one in Drive.

    Returns the file ID.
    """
    # today's date in YYYY-MM-DD format
    file_name = datetime.now().strftime('%Y-%m-%d') + '.md'
    try:
        # Search for existing file by name whithin the folder
        results = service.files().list(
            q=f"name='{file_name}' and mimeType='{MARKDOWN_MIME_TYPE}' and trashed=false and parents='{folder_id}'",
            spaces='drive',
            fields='files(id, name)',
        ).execute()
        files = results.get('files', [])
        if files:
            file_id = files[0]['id']
            logger.info(f"Found existing file: {file_name} (ID: {file_id})")
            return file_id

        # Create new file
        file_metadata = {
            'name': file_name,
            'parents': [folder_id],
            'mimeType': MARKDOWN_MIME_TYPE,
        }
        initial_content = f"# Telegram Messages\n\n"
        media = MediaInMemoryUpload(
            initial_content.encode('utf-8'),
            mimetype=MARKDOWN_MIME_TYPE,
        )
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
        ).execute()
        file_id = file.get('id')

        logger.info(f"Created new file: {file_name} (ID: {file_id})")
        return file_id
    except Exception as e:
        logger.error(f"Failed to get/create markdown file: {e}")
        return None


def append_message(
    service,
    file_id: str,
    message_id: int,
    content: str,
    timestamp: datetime,
    username: str,
) -> bool:
    """Append a new message to the markdown file in Drive."""
    try:
        # Download current file content
        logger.info(f"Downloading file content for file {file_id}")
        current_content = _download_file_content(service, file_id)
        if current_content is None:
            return False

        # Format the new message block
        message_block = _format_message_block(message_id, content)

        # Append to content
        updated_content = current_content + message_block

        # Upload updated file
        return _upload_file_content(service, file_id, updated_content)

    except Exception as e:
        logger.error(f"Failed to append message {message_id}: {e}")
        return False


def update_message(
    service,
    file_id: str,
    message_id: int,
    new_content: str,
    edit_timestamp: datetime,
) -> bool:
    """Update an existing message in the markdown file (for edited messages)."""
    try:
        current_content = _download_file_content(service, file_id)
        if current_content is None:
            return False

        updated_content = _replace_message_content(
            current_content, message_id, new_content, edit_timestamp
        )

        if updated_content is None:
            logger.warning(f"Message {message_id} not found in file for update")
            return False

        return _upload_file_content(service, file_id, updated_content)

    except Exception as e:
        logger.error(f"Failed to update message {message_id}: {e}")
        return False


def delete_message(
    service,
    file_id: str,
    message_id: int,
) -> bool:
    """Delete a message from the markdown file. Silently succeeds if message not found."""
    try:
        current_content = _download_file_content(service, file_id)
        if current_content is None:
            return False

        updated_content = _remove_message_block(current_content, message_id)
        if updated_content is None:
            logger.info(f"Message {message_id} not found in file, ignoring deletion")
            return True

        return _upload_file_content(service, file_id, updated_content)

    except Exception as e:
        logger.error(f"Failed to delete message {message_id}: {e}")
        return False


def _format_message_block(message_id: int, content: str) -> str:
    """Format a message as a comment-style markdown block."""
    return f"<!-- msg_id: {message_id} -->\n{content}\n"


def _remove_message_block(file_content: str, message_id: int) -> str | None:
    """Find and remove a message block by ID from the file content.

    Returns updated content, or None if message not found.
    """
    pattern = re.compile(rf'<!-- msg_id: {message_id} -->\n')
    match = pattern.search(file_content)
    if not match:
        return None

    block_start = match.start()
    header_end = match.end()

    next_match = MESSAGE_PATTERN.search(file_content, header_end)
    block_end = next_match.start() if next_match else len(file_content)

    return file_content[:block_start] + file_content[block_end:]


def _replace_message_content(
    file_content: str, message_id: int, new_content: str, edit_timestamp: datetime
) -> str | None:
    """Find and replace a message by ID in the file content.

    Returns updated content, or None if message not found.
    """
    # Find the message header by ID
    pattern = re.compile(
        rf'<!-- msg_id: {message_id} -->\n'
    )

    match = pattern.search(file_content)
    if not match:
        return None

    header_start = match.start()
    header_end = match.end()

    # Find the end of this message's content (next comment block or end of file)
    next_match = MESSAGE_PATTERN.search(file_content, header_end)
    content_end = next_match.start() if next_match else len(file_content)

    # Build updated block with edited timestamp
    new_header = f"<!-- msg_id: {message_id} -->\n"
    new_block = f"{new_header}{new_content}\n"

    return file_content[:header_start] + new_block + file_content[content_end:]


def _download_file_content(service, file_id: str) -> str | None:
    """Download a file's content from Drive."""
    try:
        content = service.files().get_media(fileId=file_id).execute()
        return content.decode('utf-8') if isinstance(content, bytes) else content
    except Exception as e:
        logger.error(f"Failed to download file {file_id}: {e}")
        return None


def _upload_file_content(service, file_id: str, content: str) -> bool:
    """Upload updated content to a Drive file."""
    try:
        media = MediaInMemoryUpload(
            content.encode('utf-8'),
            mimetype=MARKDOWN_MIME_TYPE,
        )
        service.files().update(
            fileId=file_id,
            media_body=media,
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to upload file {file_id}: {e}")
        return False
