"""Verify GitHub Actions OIDC bearer tokens for the nightly-trigger endpoint.

The nightly workflow (`.github/workflows/nightly-summary.yml`) requests a
short-lived OIDC ID token from GitHub and sends it as a Bearer token to
`POST /api/jobs/nightly-summary`. Verifying it here means no long-lived
secret has to be shared with the workflow at all — just an allowlist of
which repository/ref/workflow/event is trusted, checked against claims in a
token GitHub itself signed.
"""

from __future__ import annotations

import jwt
import structlog

from second_brain.core.config import get_settings

log = structlog.get_logger()

ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = f"{ISSUER}/.well-known/jwks"

# Module-level so the JWK set is fetched once and cached across requests,
# not re-fetched from GitHub on every single trigger call.
_jwk_client = jwt.PyJWKClient(JWKS_URL, cache_keys=True)


class OidcRejected(Exception):
    """The bearer token failed cryptographic/structural verification —
    bad signature, expired, wrong audience, or wrong issuer. Maps to 401."""


class PolicyRejected(Exception):
    """The token verified fine but its claims don't match our allowlist —
    wrong repository, ref, workflow, or event. Maps to 403."""


class OidcUnavailable(Exception):
    """Couldn't fetch or use GitHub's JWKS to verify the token (network
    failure, GitHub outage). Maps to 503 — retry later, not a real rejection."""


def verify_github_identity(bearer: str) -> dict:
    """Verify a GitHub Actions OIDC bearer token end to end.

    Returns the token's claims dict on success. Raises `OidcRejected`,
    `PolicyRejected`, or `OidcUnavailable` — see each class's docstring for
    which HTTP status it should map to.
    """
    settings = get_settings()

    try:
        signing_key = _jwk_client.get_signing_key_from_jwt(bearer)
    except jwt.PyJWKClientError as e:
        # Covers both "couldn't reach GitHub's JWKS endpoint" and "no
        # matching key" — either way this is an availability problem, not
        # proof the token itself is bad.
        raise OidcUnavailable(str(e)) from e
    except jwt.PyJWTError as e:
        raise OidcRejected(str(e)) from e

    try:
        claims = jwt.decode(
            bearer,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.nightly_oidc_audience,
            issuer=ISSUER,
            # The job machine resumes from Fly suspend with its clock
            # potentially lagging a few seconds until NTP resyncs, while
            # GitHub mints iat/nbf as exactly "now" — a small leeway avoids
            # spurious ImmatureSignatureError/InvalidIssuedAtError right
            # after a cold start.
            leeway=60,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except jwt.PyJWTError as e:
        raise OidcRejected(str(e)) from e

    if claims.get("repository") != settings.nightly_allowed_repository:
        raise PolicyRejected(f"unexpected repository: {claims.get('repository')!r}")

    if claims.get("ref") != settings.nightly_allowed_ref:
        raise PolicyRejected(f"unexpected ref: {claims.get('ref')!r}")

    expected_workflow_prefix = (
        f"{settings.nightly_allowed_repository}/{settings.nightly_allowed_workflow}"
        f"@{settings.nightly_allowed_ref}"
    )
    if not claims.get("workflow_ref", "").startswith(expected_workflow_prefix):
        raise PolicyRejected(f"unexpected workflow_ref: {claims.get('workflow_ref')!r}")

    if claims.get("event_name") not in {"schedule", "workflow_dispatch"}:
        raise PolicyRejected(f"unexpected event_name: {claims.get('event_name')!r}")

    return claims
