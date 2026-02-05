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