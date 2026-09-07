"""Tests for webhook's Flask routes using Flask's test client.

Deliberately does NOT start any threads or import the real bot stack
(python-telegram-bot, second_brain.bot.handlers) — routes that need
bot_app/event_loop/token_storage/Update are exercised by monkeypatching those
globals to sentinels, matching how _bot_ready() gates them in production
during the startup window before _load_bot_modules() has run.
"""
import os
import subprocess
import sys
from unittest.mock import Mock

from second_brain.bot import webhook as webhook_server
from second_brain.core.config import config


def _make_client():
    webhook_server.app.testing = True
    return webhook_server.app.test_client()


def _mark_ready(monkeypatch):
    """Make _bot_ready() return True without touching the real bot stack."""
    monkeypatch.setattr(webhook_server, 'Update', object())
    monkeypatch.setattr(webhook_server, 'bot_app', object())
    monkeypatch.setattr(webhook_server, 'event_loop', object())
    monkeypatch.setattr(webhook_server, 'token_storage', object())


def _mark_not_ready(monkeypatch):
    monkeypatch.setattr(webhook_server, 'Update', None)
    monkeypatch.setattr(webhook_server, 'bot_app', None)
    monkeypatch.setattr(webhook_server, 'event_loop', None)
    monkeypatch.setattr(webhook_server, 'token_storage', None)


def test_index_returns_200_ok():
    client = _make_client()

    resp = client.get('/')

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'ok'


def test_webhook_wrong_token_returns_403():
    client = _make_client()

    resp = client.post('/webhook/not-the-real-token', json={'update_id': 1})

    assert resp.status_code == 403


def test_webhook_not_ready_returns_503(monkeypatch):
    _mark_not_ready(monkeypatch)
    client = _make_client()

    resp = client.post(f'/webhook/{config.bot_token}', json={'update_id': 1})

    assert resp.status_code == 503


def test_webhook_ready_schedules_coroutine_once_and_returns_200(monkeypatch):
    _mark_ready(monkeypatch)
    calls = []

    def fake_run_coroutine_threadsafe(coro, loop):
        calls.append((coro, loop))
        coro.close()  # never actually run; avoids a "never awaited" warning
        return Mock()

    monkeypatch.setattr(webhook_server.asyncio, 'run_coroutine_threadsafe', fake_run_coroutine_threadsafe)
    client = _make_client()

    resp = client.post(f'/webhook/{config.bot_token}', json={'update_id': 1})

    assert resp.status_code == 200
    assert len(calls) == 1


def test_send_message_disabled_when_no_secret_configured(monkeypatch):
    monkeypatch.setattr(config, 'outbound_api_secret', None)
    client = _make_client()

    resp = client.post('/api/send-message', json={'chat_id': 1, 'text': 'hi'})

    assert resp.status_code == 503


def test_send_message_wrong_bearer_returns_401(monkeypatch):
    monkeypatch.setattr(config, 'outbound_api_secret', 'correct-secret')
    _mark_ready(monkeypatch)
    client = _make_client()

    resp = client.post(
        '/api/send-message',
        json={'chat_id': 1, 'text': 'hi'},
        headers={'Authorization': 'Bearer wrong-secret'},
    )

    assert resp.status_code == 401


def test_send_message_bad_body_returns_400(monkeypatch):
    monkeypatch.setattr(config, 'outbound_api_secret', 'correct-secret')
    _mark_ready(monkeypatch)
    client = _make_client()

    resp = client.post(
        '/api/send-message',
        json={'chat_id': 1},  # missing required 'text'
        headers={'Authorization': 'Bearer correct-secret'},
    )

    assert resp.status_code == 400


def test_oauth_callback_not_ready_returns_503(monkeypatch):
    _mark_not_ready(monkeypatch)
    client = _make_client()

    resp = client.get('/oauth/callback')

    assert resp.status_code == 503


def test_importing_webhook_does_not_import_telegram_or_handlers():
    """A fresh interpreter, not this test session's sys.modules (already
    polluted by other test modules), is the only reliable way to check this."""
    code = (
        "import sys\n"
        "import second_brain.bot.webhook\n"
        "assert 'telegram' not in sys.modules, 'telegram was imported at module load'\n"
        "assert 'second_brain.bot.handlers' not in sys.modules, 'handlers was imported at module load'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert 'OK' in result.stdout
