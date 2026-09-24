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
