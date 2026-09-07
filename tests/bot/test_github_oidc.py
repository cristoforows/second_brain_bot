from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from second_brain.bot import github_oidc
from second_brain.bot.github_oidc import (
    OidcRejected,
    OidcUnavailable,
    PolicyRejected,
    verify_github_identity,
)


class _FakeSettings:
    nightly_oidc_audience = "second-brain-bot-nightly"
    nightly_allowed_repository = "cristoforows/second_brain_bot"
    nightly_allowed_ref = "refs/heads/main"
    nightly_allowed_workflow = ".github/workflows/nightly-summary.yml"


class _FakeSigningKey:
    def __init__(self, key) -> None:
        self.key = key


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch):
    monkeypatch.setattr(github_oidc, "get_settings", lambda: _FakeSettings())


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


@pytest.fixture
def signing_key(rsa_keypair, monkeypatch):
    _private_pem, public_pem = rsa_keypair
    fake_key = _FakeSigningKey(public_pem)
    monkeypatch.setattr(github_oidc._jwk_client, "get_signing_key_from_jwt", lambda token: fake_key)
    return fake_key


def _valid_claims(**overrides) -> dict:
    now = int(time.time())
    claims = {
        "iss": github_oidc.ISSUER,
        "aud": "second-brain-bot-nightly",
        "exp": now + 300,
        "iat": now,
        "repository": "cristoforows/second_brain_bot",
        "ref": "refs/heads/main",
        "workflow_ref": "cristoforows/second_brain_bot/.github/workflows/nightly-summary.yml@refs/heads/main",
        "event_name": "schedule",
        "run_id": "123456",
        "actor": "cristoforows",
    }
    claims.update(overrides)
    return claims


def _sign(claims: dict, private_pem: bytes) -> str:
    return jwt.encode(claims, private_pem, algorithm="RS256")


def test_valid_token_returns_claims(rsa_keypair, signing_key):
    private_pem, _ = rsa_keypair
    token = _sign(_valid_claims(), private_pem)

    claims = verify_github_identity(token)

    assert claims["repository"] == "cristoforows/second_brain_bot"
    assert claims["event_name"] == "schedule"


def test_workflow_dispatch_event_is_also_accepted(rsa_keypair, signing_key):
    private_pem, _ = rsa_keypair
    token = _sign(_valid_claims(event_name="workflow_dispatch"), private_pem)

    claims = verify_github_identity(token)
    assert claims["event_name"] == "workflow_dispatch"


def test_wrong_audience_raises_oidc_rejected(rsa_keypair, signing_key):
    private_pem, _ = rsa_keypair
    token = _sign(_valid_claims(aud="some-other-audience"), private_pem)

    with pytest.raises(OidcRejected):
        verify_github_identity(token)


def test_wrong_issuer_raises_oidc_rejected(rsa_keypair, signing_key):
    private_pem, _ = rsa_keypair
    token = _sign(_valid_claims(iss="https://not-github.example"), private_pem)

    with pytest.raises(OidcRejected):
        verify_github_identity(token)


def test_expired_token_raises_oidc_rejected(rsa_keypair, signing_key):
    private_pem, _ = rsa_keypair
    now = int(time.time())
    token = _sign(_valid_claims(exp=now - 60, iat=now - 120), private_pem)

    with pytest.raises(OidcRejected):
        verify_github_identity(token)


def test_wrong_repository_raises_policy_rejected(rsa_keypair, signing_key):
    private_pem, _ = rsa_keypair
    token = _sign(_valid_claims(repository="someone-else/other-repo"), private_pem)

    with pytest.raises(PolicyRejected):
        verify_github_identity(token)


def test_wrong_ref_raises_policy_rejected(rsa_keypair, signing_key):
    private_pem, _ = rsa_keypair
    token = _sign(_valid_claims(ref="refs/heads/some-feature-branch"), private_pem)

    with pytest.raises(PolicyRejected):
        verify_github_identity(token)


def test_wrong_workflow_raises_policy_rejected(rsa_keypair, signing_key):
    private_pem, _ = rsa_keypair
    token = _sign(
        _valid_claims(
            workflow_ref="cristoforows/second_brain_bot/.github/workflows/other.yml@refs/heads/main"
        ),
        private_pem,
    )

    with pytest.raises(PolicyRejected):
        verify_github_identity(token)


def test_wrong_event_name_raises_policy_rejected(rsa_keypair, signing_key):
    private_pem, _ = rsa_keypair
    token = _sign(_valid_claims(event_name="pull_request"), private_pem)

    with pytest.raises(PolicyRejected):
        verify_github_identity(token)


def test_jwks_fetch_failure_raises_oidc_unavailable(monkeypatch):
    def _raise(token):
        raise jwt.PyJWKClientConnectionError("could not reach jwks endpoint")

    monkeypatch.setattr(github_oidc._jwk_client, "get_signing_key_from_jwt", _raise)

    with pytest.raises(OidcUnavailable):
        verify_github_identity("irrelevant-token-value")


def test_malformed_token_raises_oidc_rejected(monkeypatch):
    def _raise(token):
        raise jwt.DecodeError("not a valid token")

    monkeypatch.setattr(github_oidc._jwk_client, "get_signing_key_from_jwt", _raise)

    with pytest.raises(OidcRejected):
        verify_github_identity("not-a-real-jwt")
