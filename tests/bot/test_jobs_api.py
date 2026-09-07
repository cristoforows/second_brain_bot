"""Tests for POST /api/jobs/nightly-summary using Flask's test client.

Fakes the OIDC verifier and the Fly Machines client so no real network call,
JWT signing, or Fly API happens — this only exercises jobs_api's own
request-validation and dispatch logic.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from second_brain.bot import jobs_api
from second_brain.bot.github_oidc import OidcRejected, OidcUnavailable, PolicyRejected
from second_brain.bot.webhook import app
from second_brain.core.fly_machines import FlyMachinesError
from second_brain.core.timeutil import today


class _FakeSettings:
    fly_job_token = "job-token"
    fly_app_name = "my-app"
    fly_image_ref = "registry.fly.io/my-app:deployment-1"
    app_timezone = "Asia/Singapore"


_VALID_CLAIMS = {
    "repository": "cristoforows/second_brain_bot",
    "ref": "refs/heads/main",
    "event_name": "schedule",
    "run_id": "999",
    "actor": "github-actions",
}


def _client():
    app.testing = True
    return app.test_client()


def _auth_headers(token: str = "a-valid-looking-jwt") -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fake_settings(monkeypatch) -> _FakeSettings:
    settings = _FakeSettings()
    monkeypatch.setattr(jobs_api, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def verified(monkeypatch):
    """By default, OIDC verification succeeds and returns _VALID_CLAIMS."""
    monkeypatch.setattr(jobs_api, "verify_github_identity", lambda bearer: dict(_VALID_CLAIMS))


@pytest.fixture
def not_already_running(monkeypatch):
    monkeypatch.setattr(jobs_api.fly_machines, "summarizer_active", lambda app: False)


@pytest.fixture
def create_machine_mock(monkeypatch):
    mock = MagicMock(return_value="new-machine-id")
    monkeypatch.setattr(jobs_api.fly_machines, "create_machine", mock)
    return mock


# ---------------------------------------------------------------------------
# 503 — trigger disabled
# ---------------------------------------------------------------------------


def test_disabled_when_no_job_token(monkeypatch):
    settings = _FakeSettings()
    settings.fly_job_token = ""
    monkeypatch.setattr(jobs_api, "get_settings", lambda: settings)

    resp = _client().post("/api/jobs/nightly-summary", json={})

    assert resp.status_code == 503
    assert resp.get_json()["error"] == "nightly trigger disabled"


# ---------------------------------------------------------------------------
# 401 — missing/malformed auth
# ---------------------------------------------------------------------------


def test_missing_authorization_header_returns_401(fake_settings):
    resp = _client().post("/api/jobs/nightly-summary", json={})
    assert resp.status_code == 401


def test_malformed_authorization_header_returns_401(fake_settings):
    resp = _client().post(
        "/api/jobs/nightly-summary", json={}, headers={"Authorization": "NotBearer xyz"}
    )
    assert resp.status_code == 401


def test_empty_bearer_token_returns_401(fake_settings):
    resp = _client().post(
        "/api/jobs/nightly-summary", json={}, headers={"Authorization": "Bearer "}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# OIDC verification outcomes
# ---------------------------------------------------------------------------


def test_oidc_rejected_returns_401(fake_settings, monkeypatch):
    def _raise(bearer):
        raise OidcRejected("bad signature")

    monkeypatch.setattr(jobs_api, "verify_github_identity", _raise)

    resp = _client().post("/api/jobs/nightly-summary", json={}, headers=_auth_headers())
    assert resp.status_code == 401


def test_policy_rejected_returns_403(fake_settings, monkeypatch):
    def _raise(bearer):
        raise PolicyRejected("wrong repository")

    monkeypatch.setattr(jobs_api, "verify_github_identity", _raise)

    resp = _client().post("/api/jobs/nightly-summary", json={}, headers=_auth_headers())
    assert resp.status_code == 403


def test_oidc_unavailable_returns_503(fake_settings, monkeypatch):
    def _raise(bearer):
        raise OidcUnavailable("jwks fetch failed")

    monkeypatch.setattr(jobs_api, "verify_github_identity", _raise)

    resp = _client().post("/api/jobs/nightly-summary", json={}, headers=_auth_headers())
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# 400 — body validation
# ---------------------------------------------------------------------------


def test_unknown_body_key_returns_400(fake_settings, verified):
    resp = _client().post(
        "/api/jobs/nightly-summary", json={"unexpected": "key"}, headers=_auth_headers()
    )
    assert resp.status_code == 400


def test_invalid_date_format_returns_400(fake_settings, verified):
    resp = _client().post(
        "/api/jobs/nightly-summary", json={"date": "01-01-2026"}, headers=_auth_headers()
    )
    assert resp.status_code == 400


def test_date_after_today_returns_400(fake_settings, verified):
    future = today(fake_settings.app_timezone) + timedelta(days=1)
    resp = _client().post(
        "/api/jobs/nightly-summary",
        json={"date": future.isoformat()},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400


def test_date_too_far_in_the_past_returns_400(fake_settings, verified):
    too_old = today(fake_settings.app_timezone) - timedelta(days=31)
    resp = _client().post(
        "/api/jobs/nightly-summary",
        json={"date": too_old.isoformat()},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400


def test_date_exactly_30_days_back_is_allowed(fake_settings, verified, not_already_running, create_machine_mock):
    boundary = today(fake_settings.app_timezone) - timedelta(days=30)
    resp = _client().post(
        "/api/jobs/nightly-summary",
        json={"date": boundary.isoformat()},
        headers=_auth_headers(),
    )
    assert resp.status_code == 202


def test_dry_run_not_a_bool_returns_400(fake_settings, verified):
    resp = _client().post(
        "/api/jobs/nightly-summary", json={"dry_run": "yes"}, headers=_auth_headers()
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 409 — already running
# ---------------------------------------------------------------------------


def test_summarizer_already_active_returns_409(fake_settings, verified, monkeypatch):
    monkeypatch.setattr(jobs_api.fly_machines, "summarizer_active", lambda app: True)

    resp = _client().post("/api/jobs/nightly-summary", json={}, headers=_auth_headers())
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# 502 — Fly Machines API failure
# ---------------------------------------------------------------------------


def test_fly_machines_error_returns_502(fake_settings, verified, not_already_running, monkeypatch):
    def _raise(*args, **kwargs):
        raise FlyMachinesError(500, "internal error")

    monkeypatch.setattr(jobs_api.fly_machines, "create_machine", _raise)

    resp = _client().post("/api/jobs/nightly-summary", json={}, headers=_auth_headers())
    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# 202 — success, exact cmd/config assertions
# ---------------------------------------------------------------------------


def test_success_with_no_body_uses_defaults(fake_settings, verified, not_already_running, create_machine_mock):
    resp = _client().post("/api/jobs/nightly-summary", headers=_auth_headers())

    assert resp.status_code == 202
    data = resp.get_json()
    assert data == {"ok": True, "machine_id": "new-machine-id", "date": "yesterday", "dry_run": False}

    create_machine_mock.assert_called_once()
    call = create_machine_mock.call_args
    assert call.args == ("my-app",)
    assert call.kwargs["image"] == "registry.fly.io/my-app:deployment-1"
    assert call.kwargs["cmd"] == ["timeout", "-k", "60", "2100", "second-brain", "summarize"]
    assert call.kwargs["region"] == "sin"
    assert call.kwargs["memory_mb"] == 512
    assert call.kwargs["metadata"] == {
        "role": "summarizer",
        "triggered_by": "github",
        "run_id": "999",
        "event": "schedule",
    }


def test_success_with_date_and_dry_run(fake_settings, verified, not_already_running, create_machine_mock):
    a_recent_date = (today(fake_settings.app_timezone) - timedelta(days=3)).isoformat()

    resp = _client().post(
        "/api/jobs/nightly-summary",
        json={"date": a_recent_date, "dry_run": True},
        headers=_auth_headers(),
    )

    assert resp.status_code == 202
    data = resp.get_json()
    assert data == {"ok": True, "machine_id": "new-machine-id", "date": a_recent_date, "dry_run": True}

    call = create_machine_mock.call_args
    assert call.kwargs["cmd"] == [
        "timeout", "-k", "60", "2100",
        "second-brain", "summarize",
        "--date", a_recent_date,
        "--dry-run",
    ]


def test_route_does_not_require_bot_ready(fake_settings, verified, not_already_running, create_machine_mock):
    """Unlike /webhook/<token> and /oauth/callback, this route must work
    even before _load_bot_modules() has populated bot_app/event_loop/
    token_storage — it never touches them."""
    import second_brain.bot.webhook as webhook_module

    assert webhook_module.bot_app is None
    assert webhook_module.event_loop is None
    assert webhook_module.token_storage is None

    resp = _client().post("/api/jobs/nightly-summary", json={}, headers=_auth_headers())
    assert resp.status_code == 202
