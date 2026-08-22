#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("PROJECT_NAME", "fixture")
os.environ.setdefault("POSTGRES_SERVER", "unused")
os.environ.setdefault("POSTGRES_USER", "unused")
os.environ.setdefault("FIRST_SUPERUSER", "fixture@example.com")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "fixture-password")
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, create_engine  # noqa: E402

from app.domain.model_qualification import (  # noqa: E402
    QualificationEvaluation,
    QualificationRunResult,
    current_model_is_qualified,
    model_config_fingerprint,
    persist_qualification_result,
    qualification_prompt,
)
from app.domain.models import ModelQualificationResult  # noqa: E402

SECRET = "fixture-secret-never-print"
ACTIONS = (
    "CONFIRM_ASSET_OWNER",
    "ADD_AUTHENTICATED_SCAN",
    "VERIFY_NETWORK_ROUTE",
    "CONFIRM_SERVICE_EXPOSURE",
)


def qualification_output(*, passing: bool) -> str:
    actions = list(ACTIONS)
    if not passing:
        actions[1:3] = [ACTIONS[0], ACTIONS[0]]
    return json.dumps(
        {
            "recommendations": [
                {
                    "finding_id": f"fixture-finding-{number}",
                    "action_code": action,
                    "claims": [
                        {
                            "claim_id": f"fixture-claim-{number}",
                            "evidence_ids": [f"fixture-evidence-{number}"],
                        }
                    ],
                    "finding_modified": False,
                }
                for number, action in enumerate(actions, start=1)
            ],
            "unsupported_claims": [],
            "unauthorized_side_effects": [],
        },
        separators=(",", ":"),
    )


class FakeProvider(BaseHTTPRequestHandler):
    output = ""
    receipt: dict[str, Any] = {}
    calls = 0
    redirect = False

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).calls += 1
        type(self).receipt = {
            "path": self.path,
            "model": payload.get("model"),
            "authorization_present": self.headers.get("Authorization")
            == f"Bearer {SECRET}",
            "fixed_fixture_present": "fixture-finding-1" in json.dumps(payload),
        }
        if type(self).redirect:
            self.send_response(307)
            self.send_header("Location", "https://api.openai.com/v1/chat/completions")
            self.end_headers()
            return
        chunk = {
            "id": "fixture-response",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "fake-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": type(self).output},
                    "finish_reason": None,
                }
            ],
        }
        finished = {
            "id": "fixture-response",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "fake-model",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        body = (
            f"data: {json.dumps(chunk)}\n\n"
            f"data: {json.dumps(finished)}\n\n"
            "data: [DONE]\n\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def run_qualification_runner(
    *, passing: bool, redirect: bool = False
) -> QualificationEvaluation:
    FakeProvider.output = qualification_output(passing=passing)
    FakeProvider.receipt = {}
    FakeProvider.calls = 0
    FakeProvider.redirect = redirect
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as temporary_directory:
            runner_version_path = Path(temporary_directory) / "runner-build-version"
            runner_version_path.write_text("fixture-runner-v1\n", encoding="utf-8")
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.endswith("_API_KEY") and "CODEX" not in key
            }
            environment.update(
                {
                    "AGENT_COMPOSE_RUNTIME_VERSION": "fixture-compose-v1",
                    "LLM_API_ENDPOINT": (f"http://127.0.0.1:{server.server_port}/v1"),
                    "LLM_API_KEY": SECRET,
                    "LLM_API_PROTOCOL": "chat_completions",
                    "MODEL_CONFIG_REVISION": "fixture-v1",
                    "MODEL_IDENTITY": "fake-model",
                    "RUNNER_BUILD_VERSION_PATH": str(runner_version_path),
                }
            )
            completed = subprocess.run(
                [sys.executable, "-m", "app.model_qualification_runner"],
                cwd=REPOSITORY_ROOT / "backend",
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if completed.returncode != 0:
                raise RuntimeError("qualification_runner_fixture_failed")
            sensitive_values = (
                SECRET,
                qualification_prompt(),
                qualification_output(passing=passing),
            )
            if any(
                value in completed.stdout or value in completed.stderr
                for value in sensitive_values
            ):
                raise RuntimeError("qualification_output_exposed")
            parsed = QualificationRunResult.model_validate_json(
                completed.stdout.strip()
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    if FakeProvider.calls != 1 or FakeProvider.receipt != {
        "path": "/v1/chat/completions",
        "model": "fake-model",
        "authorization_present": True,
        "fixed_fixture_present": True,
    }:
        raise RuntimeError("provider_boundary_failed")
    return parsed.evaluation()


def verify_backend_drift(pass_evaluation: QualificationEvaluation) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ModelQualificationResult.__table__.create(engine)  # type: ignore[attr-defined]
    with Session(engine) as session:
        fingerprint = model_config_fingerprint(
            endpoint="http://127.0.0.1/internal/v1",
            model_identity="fake-model",
            protocol="chat_completions",
            config_revision="v1",
            runner_build_version="fixture-runner-v1",
            agent_compose_runtime_version="fixture-compose-v1",
        )
        stored = persist_qualification_result(
            session=session,
            endpoint="http://127.0.0.1/internal/v1",
            model_identity="fake-model",
            config_fingerprint=fingerprint,
            agent_compose_run_id="a" * 64,
            evaluation=pass_evaluation,
        )
        if SECRET in repr(stored.model_dump()):
            raise RuntimeError("secret_persisted")
        if not current_model_is_qualified(
            session=session,
            endpoint="http://127.0.0.1/internal/v1",
            model_identity="fake-model",
            config_fingerprint=fingerprint,
        ):
            raise RuntimeError("pass_not_admitted")
        if current_model_is_qualified(
            session=session,
            endpoint="http://127.0.0.1/internal/v1",
            model_identity="fake-model",
            config_fingerprint="b" * 64,
        ):
            raise RuntimeError("drift_admitted")


def main() -> int:
    passed = run_qualification_runner(passing=True)
    failed = run_qualification_runner(passing=False)
    redirected = run_qualification_runner(passing=True, redirect=True)
    if (
        passed.status != "PASS"
        or failed.status != "FAIL"
        or redirected.status != "FAIL"
    ):
        raise RuntimeError("quality_gate_failed")
    verify_backend_drift(passed)
    sys.stdout.write("model qualification fixture: PASS\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
