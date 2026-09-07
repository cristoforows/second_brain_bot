from __future__ import annotations

import json

import httpx
import pytest

from second_brain.core import fly_machines
from second_brain.core.fly_machines import FlyMachinesError, create_machine, list_machines, summarizer_active


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.machines.dev")


def test_list_machines_returns_parsed_json():
    machines = [{"id": "m1", "state": "started"}, {"id": "m2", "state": "stopped"}]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/apps/my-app/machines"
        return httpx.Response(200, json=machines)

    result = list_machines("my-app", client=_client(handler))
    assert result == machines


def test_list_machines_raises_fly_machines_error_on_non_2xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    with pytest.raises(FlyMachinesError) as exc_info:
        list_machines("my-app", client=_client(handler))
    assert exc_info.value.status_code == 500
    assert "internal error" in exc_info.value.body


def test_summarizer_active_true_when_matching_machine_is_active():
    machines = [
        {
            "id": "m1",
            "state": "started",
            "config": {"metadata": {"role": "summarizer"}},
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=machines)

    assert summarizer_active("my-app", client=_client(handler)) is True


@pytest.mark.parametrize("state", ["created", "starting", "started", "replacing"])
def test_summarizer_active_true_for_each_active_state(state):
    machines = [{"id": "m1", "state": state, "config": {"metadata": {"role": "summarizer"}}}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=machines)

    assert summarizer_active("my-app", client=_client(handler)) is True


@pytest.mark.parametrize("state", ["stopped", "destroyed", "failed"])
def test_summarizer_active_false_for_terminal_states(state):
    machines = [{"id": "m1", "state": state, "config": {"metadata": {"role": "summarizer"}}}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=machines)

    assert summarizer_active("my-app", client=_client(handler)) is False


def test_summarizer_active_false_when_no_machine_has_the_role():
    machines = [{"id": "m1", "state": "started", "config": {"metadata": {"role": "other"}}}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=machines)

    assert summarizer_active("my-app", client=_client(handler)) is False


def test_summarizer_active_false_on_empty_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    assert summarizer_active("my-app", client=_client(handler)) is False


def test_create_machine_posts_expected_body_and_returns_id():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/apps/my-app/machines"
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "new-machine-id"})

    machine_id = create_machine(
        "my-app",
        image="registry.fly.io/my-app:deployment-123",
        cmd=["second-brain", "summarize", "--date", "2026-01-01"],
        region="sin",
        memory_mb=512,
        metadata={"role": "summarizer", "triggered_by": "github"},
        client=_client(handler),
    )

    assert machine_id == "new-machine-id"
    body = captured["body"]
    assert body["region"] == "sin"
    assert body["config"]["image"] == "registry.fly.io/my-app:deployment-123"
    assert body["config"]["init"]["cmd"] == ["second-brain", "summarize", "--date", "2026-01-01"]
    assert body["config"]["auto_destroy"] is True
    assert body["config"]["restart"] == {"policy": "no"}
    assert body["config"]["guest"] == {"cpu_kind": "shared", "cpus": 1, "memory_mb": 512}
    assert body["config"]["metadata"] == {"role": "summarizer", "triggered_by": "github"}


def test_create_machine_raises_fly_machines_error_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text='{"error": "invalid region"}')

    with pytest.raises(FlyMachinesError) as exc_info:
        create_machine(
            "my-app",
            image="img",
            cmd=["second-brain", "summarize"],
            region="bogus",
            memory_mb=512,
            metadata={},
            client=_client(handler),
        )
    assert exc_info.value.status_code == 422


def test_build_client_uses_settings(monkeypatch):
    """When no client is injected, one is built from Settings (base URL + bearer token)."""
    settings = fly_machines.get_settings()
    monkeypatch.setattr(settings, "fly_api_base", "https://fake.example")
    monkeypatch.setattr(settings, "fly_job_token", "secret-token")
    monkeypatch.setattr(fly_machines, "get_settings", lambda: settings)

    client = fly_machines._build_client()
    try:
        assert str(client.base_url) == "https://fake.example"
        assert client.headers["authorization"] == "Bearer secret-token"
    finally:
        client.close()
