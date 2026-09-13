from types import SimpleNamespace
from typing import Any

import pytest

from app.domain import model_connections as service
from app.integrations import model_connection_runtime as runtime


def test_only_empty_docker_projection_is_equivalent() -> None:
    submitted = {
        "agents": [{"name": "worker", "driver": {"name": "docker", "docker": {}}}]
    }
    stored = {"agents": [{"name": "worker", "driver": {"name": "docker"}}]}
    assert runtime.normalized_projection(submitted) == stored
    assert "docker" in submitted["agents"][0]["driver"]
    changed = {
        "agents": [
            {
                "name": "worker",
                "driver": {"name": "docker", "docker": {"network": "other"}},
            }
        ]
    }
    assert runtime.normalized_projection(changed) != stored
    other_driver = {
        "agents": [{"name": "worker", "driver": {"name": "boxlite", "boxlite": {}}}]
    }
    assert runtime.normalized_projection(other_driver) != stored


def _version(**overrides: object) -> Any:
    values: dict[str, Any] = {
        "id": "version-id",
        "runtime_project_name": "exposure-model-version-id",
        "model_identity": "fixture-model",
        "runner_build_version": "runner-v1",
        "runtime_version": "runtime-v1",
        "runtime_spec_hash": None,
        "runtime_project_id": None,
        "runtime_project_revision": None,
        "runtime_agents": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _Client:
    project_id = "project-id"

    def __init__(self, responses: list[dict[str, object] | None]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _request(self, path: str, payload: dict[str, object], **_kwargs: object) -> dict[str, object] | None:
        self.calls.append((path, payload))
        return self.responses.pop(0)


def test_ensure_project_creates_and_attests_exact_native_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version = _version()
    spec = runtime.project_spec(version)
    agents = {role: f"agent-{role}" for role in runtime.ROLES}
    observed: Any = {
        "project": {
            "summary": {
                "projectId": "project-id",
                "name": version.runtime_project_name,
                "currentRevision": "1",
                "specHash": "sha256:fixture",
            },
            "spec": runtime.normalized_projection(spec),
            "agents": [
                {"agentName": role, "managedAgentId": agent}
                for role, agent in agents.items()
            ],
        }
    }
    client = _Client(
        [
            {"valid": True},
            {"revision": {"spec": spec, "specHash": "sha256:fixture"}},
            None,
            {"ignored": True},
            observed,
        ]
    )
    monkeypatch.setattr(runtime, "client_for_version", lambda _: client)

    assert runtime.ensure_project(version, create=True) == {
        "spec_hash": "sha256:fixture",
        "project_id": "project-id",
        "project_revision": "1",
        "agents": agents,
    }
    assert [call[0] for call in client.calls].count(
        "/agentcompose.v2.ProjectService/ApplyProject"
    ) == 2


@pytest.mark.parametrize(
    "responses",
    [
        [{"valid": False}],
        [{"valid": True}, {"revision": {}}],
        [{"valid": True}, {"revision": {"spec": {}, "specHash": "sha256:x"}}, None],
    ],
)
def test_ensure_project_rejects_invalid_or_missing_native_state(
    monkeypatch: pytest.MonkeyPatch, responses: list[dict[str, object] | None]
) -> None:
    monkeypatch.setattr(runtime, "client_for_version", lambda _: _Client(responses))
    with pytest.raises(service.ModelConnectionError):
        runtime.ensure_project(_version(), create=False)
