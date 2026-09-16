import os
import re
import subprocess
from pathlib import Path

import pytest

from app.core.config import settings
from app.domain.model_qualification import model_config_fingerprint


def test_governance_runner_build_version_falls_back_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "legacy")
    monkeypatch.setattr(settings, "GOVERNANCE_RUNNER_BUILD_VERSION", None)
    assert settings.governance_runner_build_version == "legacy"


def test_governance_runner_build_version_falls_back_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "legacy")
    monkeypatch.setattr(settings, "GOVERNANCE_RUNNER_BUILD_VERSION", "")
    assert settings.governance_runner_build_version == "legacy"


def test_governance_runner_build_version_can_override_without_changing_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "legacy")
    monkeypatch.setattr(settings, "GOVERNANCE_RUNNER_BUILD_VERSION", "governance")
    assert settings.governance_runner_build_version == "governance"
    assert settings.RUNNER_BUILD_VERSION == "legacy"


def test_model_binding_is_unchanged_by_governance_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "legacy-model")
    monkeypatch.setattr(
        settings, "MODEL_CONNECTION_RUNNER_BUILD_VERSION", "managed-model"
    )

    def fingerprint() -> str:
        return model_config_fingerprint(
            endpoint="http://127.0.0.1:9/v1",
            model_identity="fixture",
            protocol="responses",
            config_revision="v1",
            runner_build_version=settings.RUNNER_BUILD_VERSION,
            agent_compose_runtime_version="runtime",
        )

    before = fingerprint()
    monkeypatch.setattr(settings, "GOVERNANCE_RUNNER_BUILD_VERSION", "new-governance")
    assert settings.governance_runner_build_version == "new-governance"
    assert fingerprint() == before
    assert settings.MODEL_CONNECTION_RUNNER_BUILD_VERSION == "managed-model"


def test_render_changes_only_the_governance_agent(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    template = root / "agent-compose.yml"
    names = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)\}", template.read_text()))
    env = {**os.environ, **dict.fromkeys(names, "synthetic")}
    env.update(
        DOCKER_IMAGE_RUNNER="fixture-runner",
        RUNNER_BUILD_VERSION="legacy",
        ARTIFACT_HOST_PATH=str(tmp_path),
    )

    def render(override: str | None) -> str:
        if override is None:
            env.pop("GOVERNANCE_RUNNER_BUILD_VERSION", None)
        else:
            env["GOVERNANCE_RUNNER_BUILD_VERSION"] = override
        output = tmp_path / "render.yml"
        subprocess.run(
            [
                "sh",
                str(root / "scripts/render-agent-compose-config.sh"),
                str(template),
                str(output),
            ],
            env=env,
            check=True,
            capture_output=True,
        )
        return output.read_text()

    default = render(None)
    assert render("") == default
    override = render("new-governance")
    before_governance, before_models = default.split("  model-qualifier:", 1)
    after_governance, after_models = override.split("  model-qualifier:", 1)
    assert before_models == after_models
    assert after_governance == before_governance.replace(
        "fixture-runner:legacy", "fixture-runner:new-governance"
    ).replace("RUNNER_BUILD_VERSION: legacy", "RUNNER_BUILD_VERSION: new-governance")
    assert default.count("image: fixture-runner:legacy") == 5
    assert override.count("image: fixture-runner:legacy") == 4


def test_governance_image_build_mismatch_is_still_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import hashlib

    from app.governance_runner import main
    from tests.domain.test_governance_run_input_contract import _pinned

    pinned = _pinned()
    environment = pinned.runner_environment(
        trigger_id="synthetic-trigger",
        requested_by="synthetic-operator",
        input_hash=pinned.input_hash(),
    )
    environment["SANDBOX_ID"] = hashlib.sha256(b"synthetic-session").hexdigest()
    build = tmp_path / "runner-build-version"
    build.write_text("a-different-physical-build")
    environment["RUNNER_BUILD_VERSION_PATH"] = str(build)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    assert main() == 1
    assert "runner_build_version_mismatch" in caplog.text
