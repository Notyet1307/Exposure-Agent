"""Supervisor boundary tests; the real pinned Pi lifecycle is exercised in its image."""

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.integrations import pi_investigation as runtime

_OUTPUT = {
    "facts": [{"text": "Observed", "citation_ids": ["citation-1"]}],
    "explanations": [],
    "gaps": [],
    "next_steps": [],
}
_CALL = {
    "type": "toolCall",
    "id": "call-1",
    "name": "read_asset_facts",
    "arguments": {},
}


def _child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, program: str) -> None:
    child = tmp_path / "boundary-child"
    child.write_text(
        f"#!{sys.executable}\n"
        "import json, os, urllib.request, urllib.error, time\n"
        "def request(path, body):\n"
        "    req = urllib.request.Request(os.environ['INVESTIGATION_BRIDGE'] + path, "
        "data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + "
        "os.environ['INVESTIGATION_CAPABILITY'], 'Content-Type':'application/json'})\n"
        "    try:\n"
        "        with urllib.request.urlopen(req) as response: return json.load(response)\n"
        "    except urllib.error.HTTPError: return None\n" + program,
        encoding="utf-8",
    )
    child.chmod(0o700)
    monkeypatch.setattr(runtime, "_PI", str(child))


def _run(reads: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    def facts(args: dict[str, Any]) -> dict[str, Any]:
        reads.append(args)
        return {"citation_ids": ["citation-1"], "observed": True}

    options: dict[str, Any] = {
        "binding": SimpleNamespace(
            endpoint="http://provider.invalid/v1",
            resolved_address="127.0.0.1",
            protocol="chat_completions",
            model_identity="fixture",
        ),
        "api_key": "upstream-only-secret",
        "read_facts": facts,
        "timeout_seconds": 3,
        "max_tool_calls": 2,
        "max_material_bytes": 1024,
        "max_output_bytes": 4096,
    }
    options.update(overrides)
    return runtime.run_pi_investigation(**options)


def test_runner_configuration_failure_does_not_expose_credentials() -> None:
    secret = "synthetic-secret-must-not-appear"
    completed = subprocess.run(
        [sys.executable, "-m", "app.ai_investigation_runner"],
        env={**os.environ, "NETFLOW_MAX_BYTES": secret, "SECRET_KEY": secret},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 1
    assert secret not in completed.stdout + completed.stderr
    assert "Traceback" not in completed.stderr


def test_authorized_tool_material_and_credentials_are_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "database-secret")
    monkeypatch.setenv("MODEL_API_KEY", "upstream-only-secret")
    monkeypatch.setenv("NODE_OPTIONS", "--require=/untrusted.js")
    _child(
        tmp_path,
        monkeypatch,
        "assert not any(k in os.environ for k in ['POSTGRES_PASSWORD','MODEL_API_KEY','NODE_OPTIONS'])\n"
        f"request('/assistant', [{_CALL!r}])\n"
        "material = request('/read_asset_facts', {'id':'call-1','arguments':{}})\n"
        "assert material['citation_ids'] == ['citation-1']\n"
        f"print({json.dumps(_OUTPUT)!r})\n",
    )
    reads: list[dict[str, Any]] = []
    assert _run(reads) == _OUTPUT
    assert reads == [{}]


@pytest.mark.parametrize(
    "calls",
    [
        [{**_CALL, "arguments": {"resource_id": "another-asset"}}],
        [{**_CALL, "name": "bash"}],
    ],
)
def test_out_of_scope_calls_fail_before_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    calls: list[dict[str, Any]],
) -> None:
    _child(tmp_path, monkeypatch, f"request('/assistant', {calls!r})\nprint('{{}}')\n")
    reads: list[dict[str, Any]] = []
    with pytest.raises(ValueError, match="^tool_scope_denied$"):
        _run(reads)
    assert reads == []


def test_parallel_tool_batch_cannot_exceed_call_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = [_CALL, {**_CALL, "id": "call-2"}]
    _child(tmp_path, monkeypatch, f"request('/assistant', {calls!r})\nprint('{{}}')\n")
    reads: list[dict[str, Any]] = []
    with pytest.raises(ValueError, match="^tool_call_limit$"):
        _run(reads, max_tool_calls=1)
    assert reads == []


def test_material_budget_is_cumulative_and_failure_is_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _child(
        tmp_path,
        monkeypatch,
        f"request('/assistant', [{_CALL!r}, {{**{_CALL!r}, 'id':'call-2'}}])\n"
        "assert request('/read_asset_facts', {'id':'call-1','arguments':{}}) is not None\n"
        "assert request('/read_asset_facts', {'id':'call-2','arguments':{}}) is None\n"
        f"print({json.dumps(_OUTPUT)!r})\n",
    )
    reads: list[dict[str, Any]] = []
    with pytest.raises(ValueError, match="^material_limit$"):
        _run(reads, max_material_bytes=70)
    assert reads == [{}, {}]


def test_callback_exception_cannot_become_success_or_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _child(
        tmp_path,
        monkeypatch,
        f"request('/assistant', [{_CALL!r}])\n"
        "request('/read_asset_facts', {'id':'call-1','arguments':{}})\n"
        f"print({json.dumps(_OUTPUT)!r})\n",
    )

    def broken(_args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("database-password and raw customer content")

    with pytest.raises(ValueError, match="^tool_failed$"):
        _run([], read_facts=broken)
    assert capsys.readouterr() == ("", "")


def test_final_json_without_a_successful_tool_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _child(tmp_path, monkeypatch, f"print({json.dumps(_OUTPUT)!r})\n")
    with pytest.raises(ValueError, match="^tool_required$"):
        _run([])


def test_total_deadline_stops_a_silent_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _child(tmp_path, monkeypatch, "time.sleep(60)\n")
    started = time.monotonic()
    with pytest.raises(ValueError, match="^investigation_timeout$"):
        _run([], timeout_seconds=0.2)
    assert time.monotonic() - started < 2


def test_output_flood_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _child(tmp_path, monkeypatch, "print('x' * 1000000)\n")
    with pytest.raises(ValueError, match="^output_limit$"):
        _run([])


def test_provider_destination_is_pinned_and_redirects_never_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, str | None, str | None]] = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers["Content-Length"]))
            requests.append(
                (self.path, self.headers.get("Host"), self.headers.get("Authorization"))
            )
            self.send_response(307)
            self.send_header(
                "Location", f"http://127.0.0.1:{server.server_port}/redirected"
            )
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _child(
        tmp_path,
        monkeypatch,
        "request('/chat/completions', {'model':'fixture'})\n"
        f"print({json.dumps(_OUTPUT)!r})\n",
    )
    try:
        with pytest.raises(ValueError, match="^model_run_failed$"):
            _run(
                [],
                binding=SimpleNamespace(
                    endpoint=f"http://unresolvable.invalid:{server.server_port}/v1",
                    resolved_address="127.0.0.1",
                    protocol="chat_completions",
                    model_identity="fixture",
                ),
            )
        assert requests == [
            (
                "/v1/chat/completions",
                f"unresolvable.invalid:{server.server_port}",
                "Bearer upstream-only-secret",
            )
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
