#!/usr/bin/env python3
"""Real agent-compose session lifecycle probe for Exposure-Agent issue #34.

The probe deliberately exercises the agent-compose control plane, rather than
modeling it locally. Its JSON report excludes credentials, guest transcripts,
and all temporary/container paths.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

CONTROL_IMAGE: Final = (
    "ghcr.io/chaitin/agent-compose@"
    "sha256:838452756fe1f71b0f4239c02068700c3f15c8cf8ffade1a09ba08837669f89e"
)
GUEST_IMAGE: Final = (
    "ghcr.io/chaitin/agent-compose-guest@"
    "sha256:99a031b38be9e6afc5b7ce5161a4c5ee6f93c9990f3b39a3fbd8c9b29044ee32"
)
CONTROL_VERSION: Final = "v2607.10.0"
CONTROL_REVISION: Final = "e14c4dbd5e3b0dec6178073902d67d2765390427"
GUEST_RUNTIME_VERSION: Final = "0.7.0"
PROJECT_NAME: Final = "exposure-agent-issue-34"


class SessionObservation(StrEnum):
    TERMINAL = "terminal"
    RUNNING = "running"
    UNKNOWN = "unknown"


class RecoveryAction(StrEnum):
    RESUME_SAME_SESSION = "resume_same_session"
    HOLD_PROJECT_RUN_SLOT = "hold_project_run_slot"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def classify_session(
    sandbox_status: str | None, *, control_plane_reachable: bool
) -> SessionObservation:
    """Classify only from a successful authoritative control-plane response."""
    if not control_plane_reachable:
        return SessionObservation.UNKNOWN
    if sandbox_status in {"stopped", "failed"}:
        return SessionObservation.TERMINAL
    if sandbox_status == "running":
        return SessionObservation.RUNNING
    return SessionObservation.UNKNOWN


def recovery_action(observation: SessionObservation) -> RecoveryAction:
    """The minimal ADR-0004 mapping; UNKNOWN and RUNNING never create a replacement."""
    if observation is SessionObservation.TERMINAL:
        return RecoveryAction.RESUME_SAME_SESSION
    return RecoveryAction.HOLD_PROJECT_RUN_SLOT


def redact_report(value: dict[str, Any]) -> dict[str, Any]:
    """Keep stable protocol facts; discard paths, credentials, and guest output."""
    forbidden = {"workspace", "token", "guest_output", "stdout", "stderr", "path"}
    return {key: item for key, item in value.items() if key not in forbidden}


def _run(command: list[str], *, check: bool = True) -> CommandResult:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    result = CommandResult(completed.returncode, completed.stdout, completed.stderr)
    if check and result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command[:3])}"
        )
    return result


def _json(result: CommandResult) -> dict[str, Any]:
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("control plane did not return JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("control plane JSON was not an object")
    return parsed


def _write_project(root: Path) -> None:
    (root / "agent-compose.yml").write_text(
        "\n".join(
            (
                f"name: {PROJECT_NAME}",
                "agents:",
                "  guest:",
                "    provider: codex",
                f"    image: {GUEST_IMAGE}",
                "    driver:",
                "      docker: {}",
                "",
            )
        ),
        encoding="utf-8",
    )


def _start_control_plane(root: Path, name: str) -> str:
    _run(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            name,
            "--publish",
            "127.0.0.1::7410",
            "--volume",
            "/var/run/docker.sock:/var/run/docker.sock",
            "--volume",
            f"{root / 'data'}:/data",
            "--volume",
            f"{root}:/probe:ro",
            CONTROL_IMAGE,
        ]
    )
    for _ in range(30):
        result = _daemon_command(name, ["status", "--json"], check=False)
        if result.returncode == 0:
            return name
        time.sleep(1)
    raise RuntimeError("control plane did not become ready")


def _stop_control_plane(name: str) -> None:
    _run(["docker", "rm", "--force", name], check=False)


def _daemon_command(
    container: str, arguments: list[str], *, check: bool = True
) -> CommandResult:
    return _run(
        [
            "docker",
            "exec",
            container,
            "agent-compose",
            "--host",
            "http://127.0.0.1:7410",
            *arguments,
        ],
        check=check,
    )


def _external_status(port: str) -> CommandResult:
    return _run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "agent-compose",
            CONTROL_IMAGE,
            "--host",
            f"http://host.docker.internal:{port}",
            "status",
            "--json",
        ],
        check=False,
    )


def _mapped_port(container: str) -> str:
    output = _run(["docker", "port", container, "7410/tcp"]).stdout.strip()
    prefix = "127.0.0.1:"
    if not output.startswith(prefix):
        raise RuntimeError("control plane did not publish a loopback port")
    return output.removeprefix(prefix)


def _sandboxes(container: str) -> list[dict[str, Any]]:
    response = _json(
        _daemon_command(
            container,
            ["--file", "/probe/agent-compose.yml", "ps", "--all", "--json"],
        )
    )
    sandboxes = response.get("sandboxes")
    if not isinstance(sandboxes, list):
        raise RuntimeError("ps response has no sandboxes list")
    return [sandbox for sandbox in sandboxes if isinstance(sandbox, dict)]


def _sandbox_for_run(container: str, run_id: str) -> dict[str, Any]:
    for _ in range(30):
        for sandbox in _sandboxes(container):
            if sandbox.get("run_id") == run_id:
                return sandbox
        time.sleep(1)
    raise RuntimeError("run never acquired a sandbox")


def _wait_for_status(container: str, run_id: str, wanted: set[str]) -> dict[str, Any]:
    for _ in range(30):
        sandbox = _sandbox_for_run(container, run_id)
        if sandbox.get("status") in wanted:
            return sandbox
        time.sleep(1)
    raise RuntimeError("control plane did not report the expected sandbox status")


def _start_detached_run(container: str, command: str) -> dict[str, Any]:
    return _json(
        _daemon_command(
            container,
            [
                "--file",
                "/probe/agent-compose.yml",
                "run",
                "guest",
                "--command",
                command,
                "--detach",
                "--json",
            ],
        )
    )


def _run_summary(container: str, run_id: str) -> dict[str, Any]:
    summary = _json(
        _daemon_command(
            container,
            [
                "--file",
                "/probe/agent-compose.yml",
                "inspect",
                "run",
                run_id,
                "--json",
            ],
        )
    )
    status = summary.get("status")
    exit_code = summary.get("exit_code")
    if not isinstance(status, str) or not isinstance(exit_code, int):
        raise RuntimeError("inspect run response has no status and exit_code")
    return {"run_status": status, "exit_code": exit_code}


def _resume(container: str, sandbox_id: str) -> CommandResult:
    return _daemon_command(
        container,
        ["--file", "/probe/agent-compose.yml", "resume", sandbox_id, "--json"],
        check=False,
    )


def _require_outage_query_failure(result: CommandResult) -> None:
    """Ensure the injected outage rejected the authoritative query."""
    if result.returncode == 0:
        raise RuntimeError("outage status query unexpectedly succeeded")


def _resumed_session_id(result: CommandResult) -> str:
    """Parse and validate the one same-session resume result."""
    if result.returncode != 0:
        raise RuntimeError(f"resume failed with exit code {result.returncode}")
    results = _json(result).get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise RuntimeError("resume response did not contain exactly one result")
    resumed = results[0]
    if not isinstance(resumed, dict):
        raise RuntimeError("resume result was not an object")
    session_id = resumed.get("sandbox_id")
    if not isinstance(session_id, str) or not session_id:
        raise RuntimeError("resume result did not contain a sandbox_id")
    if resumed.get("status") != "resumed":
        raise RuntimeError("resume result did not report resumed status")
    return session_id


def _require_same_session(original: str, resumed: str, *, call: str) -> None:
    if resumed != original:
        raise RuntimeError(f"{call} replaced the original session")


def _event(
    sandbox: dict[str, Any],
    *,
    reachable: bool,
    resume_result: CommandResult | None = None,
) -> dict[str, Any]:
    status = sandbox.get("status")
    observed = classify_session(
        status if isinstance(status, str) else None, control_plane_reachable=reachable
    )
    event: dict[str, Any] = {
        "session_id": sandbox.get("sandbox_id"),
        "sandbox_status": status,
        "observation": observed,
        "recovery_action": recovery_action(observed),
    }
    if resume_result is not None:
        event["resume_returncode"] = resume_result.returncode
    return redact_report(event)


def run_probe() -> dict[str, Any]:
    """Run success, failure, caller-loss, outage, and same-ID resume scenarios."""
    if shutil.which("docker") is None:
        raise RuntimeError("docker is required for the real control-plane probe")

    run_nonce = uuid.uuid4().hex[:12]
    first_control = f"issue34-control-{run_nonce}"
    second_control = f"issue34-restarted-{run_nonce}"
    with tempfile.TemporaryDirectory(prefix="issue34-agent-compose-") as directory:
        root = Path(directory)
        (root / "data").mkdir()
        _write_project(root)
        control = _start_control_plane(root, first_control)
        try:
            daemon_status = _json(_daemon_command(control, ["status", "--json"]))
            _json(
                _daemon_command(
                    control,
                    ["--file", "/probe/agent-compose.yml", "up", "--json"],
                )
            )

            succeeded = _start_detached_run(control, "printf issue34-success")
            success_sandbox = _wait_for_status(
                control, succeeded["id"], {"stopped", "failed"}
            )
            success_run = _run_summary(control, succeeded["id"])
            failed = _start_detached_run(control, "exit 17")
            failed_sandbox = _wait_for_status(
                control, failed["id"], {"stopped", "failed"}
            )
            failed_run = _run_summary(control, failed["id"])

            caller_lost = _start_detached_run(
                control, "sleep 8; printf issue34-caller-loss"
            )
            running_sandbox = _wait_for_status(control, caller_lost["id"], {"running"})
            session_count_before_outage = len(_sandboxes(control))
            port = _mapped_port(control)
            _stop_control_plane(control)
            outage = _external_status(port)
            _require_outage_query_failure(outage)
            control = _start_control_plane(root, second_control)
            recovered_running = _wait_for_status(
                control, caller_lost["id"], {"running", "stopped", "failed"}
            )
            session_count_after_restart = len(_sandboxes(control))
            unknown_event = {
                "control_plane_reachable": False,
                "outage_query_returncode": outage.returncode,
                "observation": SessionObservation.UNKNOWN,
                "recovery_action": recovery_action(SessionObservation.UNKNOWN),
                "session_count_before_outage": session_count_before_outage,
                "session_count_after_restart": session_count_after_restart,
                "replacement_session_started": session_count_after_restart
                > session_count_before_outage,
            }

            session_count_before_resume = session_count_after_restart
            resume_once = _resume(control, success_sandbox["sandbox_id"])
            first_resumed_session_id = _resumed_session_id(resume_once)
            _require_same_session(
                success_sandbox["sandbox_id"],
                first_resumed_session_id,
                call="first terminal resume",
            )
            resumed = _wait_for_status(
                control, succeeded["id"], {"running", "stopped", "failed"}
            )
            resumed_session_id = resumed.get("sandbox_id")
            if not isinstance(resumed_session_id, str):
                raise RuntimeError("resumed session was not returned by authoritative query")
            _require_same_session(
                first_resumed_session_id,
                resumed_session_id,
                call="post-resume authoritative query",
            )
            resume_twice = _resume(control, success_sandbox["sandbox_id"])
            repeated_resumed_session_id = _resumed_session_id(resume_twice)
            _require_same_session(
                success_sandbox["sandbox_id"],
                repeated_resumed_session_id,
                call="repeated terminal resume",
            )
            resume_failed = _resume(control, failed_sandbox["sandbox_id"])
            failure_resumed_session_id = _resumed_session_id(resume_failed)
            _require_same_session(
                failed_sandbox["sandbox_id"],
                failure_resumed_session_id,
                call="failed-session terminal resume",
            )
            session_count_after_retries = len(_sandboxes(control))
            _daemon_command(
                control,
                [
                    "--file",
                    "/probe/agent-compose.yml",
                    "stop",
                    success_sandbox["sandbox_id"],
                    "--json",
                ],
                check=False,
            )
            _daemon_command(
                control,
                [
                    "--file",
                    "/probe/agent-compose.yml",
                    "stop",
                    failed_sandbox["sandbox_id"],
                    "--json",
                ],
                check=False,
            )
            _daemon_command(
                control,
                [
                    "--file",
                    "/probe/agent-compose.yml",
                    "rm",
                    failed_sandbox["sandbox_id"],
                    "--json",
                ],
            )
            resume_missing = _resume(control, failed_sandbox["sandbox_id"])
            if resume_missing.returncode != 2:
                raise RuntimeError(
                    "missing session resume did not return the expected stable failure"
                )

            return {
                "control_plane": {
                    "image": CONTROL_IMAGE,
                    "version": daemon_status["data"]["version"],
                    "source_revision": CONTROL_REVISION,
                },
                "guest": {
                    "image": GUEST_IMAGE,
                    "runtime_version": GUEST_RUNTIME_VERSION,
                },
                "query": {
                    "entrypoint": "agent-compose ps --all --json",
                    "status_field": "sandboxes[].status",
                    "run_entrypoint": "agent-compose inspect run <run-id> --json",
                    "run_fields": ["status", "exit_code"],
                    "terminal_values_observed": sorted(
                        {success_sandbox["status"], failed_sandbox["status"]}
                    ),
                },
                "scenarios": {
                    "guest_success": _event(success_sandbox, reachable=True)
                    | success_run,
                    "guest_failure": _event(failed_sandbox, reachable=True)
                    | failed_run,
                    "caller_loss": _event(running_sandbox, reachable=True),
                    "control_plane_outage": unknown_event,
                    "after_control_plane_restart": _event(
                        recovered_running, reachable=True
                    ),
                    "resume": {
                        "original_session_id": success_sandbox["sandbox_id"],
                        "first_response_session_id": first_resumed_session_id,
                        "session_id_after_first_resume": resumed_session_id,
                        "repeated_response_session_id": repeated_resumed_session_id,
                        "failure_terminal_response_session_id": failure_resumed_session_id,
                        "same_session_id": success_sandbox["sandbox_id"]
                        == resumed_session_id,
                        "first_call_returncode": resume_once.returncode,
                        "repeated_call_returncode": resume_twice.returncode,
                        "failure_terminal_call_returncode": resume_failed.returncode,
                        "missing_session_call_returncode": resume_missing.returncode,
                        "session_count_unchanged_by_retries": session_count_before_resume
                        == session_count_after_retries,
                        "resume_source_status": success_sandbox["status"],
                    },
                },
                "minimal_mapping": {
                    "stopped_or_failed_from_successful_query": "terminal; resume same session may be attempted",
                    "running_from_successful_query": "still executing; retain the Project single-Run slot",
                    "control_plane_error_or_unrecognized_status": "unknown; retain the Project single-Run slot and do not start a replacement session",
                },
            }
        finally:
            _stop_control_plane(first_control)
            _stop_control_plane(second_control)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write the redacted JSON report")
    arguments = parser.parse_args(argv)
    report = run_probe()
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(serialized, encoding="utf-8")
    sys.stdout.write(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
