"""Session-wide pytest setup.

core.config's Settings hard-exits (sys.exit(1)) if certain env vars are
missing. Locally this repo has a real .env with real values that
pydantic-settings' env_file loading picks up, so tests never notice. CI (and
any other environment without a local .env) has none of that, so we set safe
dummy values here — but only as defaults, via setdefault(), so a real .env
(or real environment) is never overridden.
"""
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

_DEFAULTS = {
    "TELEGRAM_BOT_TOKEN": "123456:dummy-test-token-not-a-real-bot-token",
    "GOOGLE_CLIENT_ID": "dummy-client-id.apps.googleusercontent.com",
    "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "OPENROUTER_API_KEY": "dummy-openrouter-api-key",
}

for _key, _value in _DEFAULTS.items():
    os.environ.setdefault(_key, _value)


FIXTURES_DIR = Path(__file__).parent / "summarizer" / "fixtures"


@pytest.fixture
def sample_dump_path() -> Path:
    return FIXTURES_DIR / "sample_dump.md"


@pytest.fixture
def sample_dump_text(sample_dump_path: Path) -> str:
    return sample_dump_path.read_text()
