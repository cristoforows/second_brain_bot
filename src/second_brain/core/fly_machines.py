"""Minimal Fly Machines API client.

Used by the nightly-trigger endpoint (`bot.jobs_api`) to start the
summarizer as a one-off machine instead of shelling out to `flyctl`. Every
function accepts an optional `client` for injecting a fake/mocked
`httpx.Client` in tests; production callers omit it and get one built from
`core.config.Settings` (base URL + bearer token).
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from second_brain.core.config import get_settings

log = structlog.get_logger()

_TIMEOUT = 30.0

# Machine states that mean "a summarizer machine is already doing something"
# — not yet a terminal state (stopped/destroyed/failed don't block a new run).
_ACTIVE_STATES = {"created", "starting", "started", "replacing"}


class FlyMachinesError(RuntimeError):
    """A Fly Machines API call returned a non-2xx response."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        excerpt = body[:500]
        super().__init__(f"Fly Machines API error {status_code}: {excerpt}")


def _build_client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        base_url=settings.fly_api_base,
        headers={"Authorization": f"Bearer {settings.fly_job_token}"},
        timeout=_TIMEOUT,
    )


def _request(method: str, path: str, *, client: httpx.Client | None = None, **kwargs: Any) -> Any:
    """Issue one request, closing the client afterward only if we built it."""
    owns_client = client is None
    active_client = client or _build_client()
    try:
        response = active_client.request(method, path, **kwargs)
    finally:
        if owns_client:
            active_client.close()

    if not (200 <= response.status_code < 300):
        raise FlyMachinesError(response.status_code, response.text)
    if not response.content:
        return None
    return response.json()


def list_machines(app: str, *, client: httpx.Client | None = None) -> list[dict]:
    """List all machines for a Fly app."""
    result = _request("GET", f"/v1/apps/{app}/machines", client=client)
    return result or []


def summarizer_active(app: str, *, client: httpx.Client | None = None) -> bool:
    """True if a summarizer machine already exists in a non-terminal state.

    Used to avoid starting a second summarizer run while one is still going.
    """
    for machine in list_machines(app, client=client):
        config = machine.get("config") or {}
        metadata = config.get("metadata") or {}
        if metadata.get("role") == "summarizer" and machine.get("state") in _ACTIVE_STATES:
            return True
    return False


def create_machine(
    app: str,
    *,
    image: str,
    cmd: list[str],
    region: str,
    memory_mb: int,
    metadata: dict,
    client: httpx.Client | None = None,
) -> str:
    """Create a one-off Fly machine that auto-destroys on exit and is never
    restarted by Fly itself. Returns the new machine's id."""
    body = {
        "region": region,
        "config": {
            "image": image,
            "init": {"cmd": cmd},
            "auto_destroy": True,
            "restart": {"policy": "no"},
            "guest": {"cpu_kind": "shared", "cpus": 1, "memory_mb": memory_mb},
            "metadata": metadata,
        },
    }
    result = _request("POST", f"/v1/apps/{app}/machines", client=client, json=body)
    machine_id = result["id"]
    log.info("fly_machine_created", app=app, machine_id=machine_id, metadata=metadata)
    return machine_id
