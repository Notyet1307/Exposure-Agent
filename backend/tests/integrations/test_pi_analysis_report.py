import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.integrations import pi_investigation as runtime
from tests.integrations.test_pi_investigation import _child


def _options(**extra: Any) -> dict[str, Any]:
    return {
        "binding": SimpleNamespace(
            endpoint="http://provider.invalid/v1",
            resolved_address="127.0.0.1",
            protocol="chat_completions",
            model_identity="fixture",
        ),
        "api_key": "provider-only-secret",
        "task": "analysis_report",
        "before_model_call": lambda: None,
        "tools": {
            "read_report_material": lambda args: {
                "items": [{"citation_id": "report:fixed"}],
                "summary": {"count": 0},
            }
        },
        "timeout_seconds": 3,
        "max_tool_calls": 2,
        "max_material_bytes": 1024,
        "max_output_bytes": 4096,
        **extra,
    }


def test_report_uses_only_fixed_material_tool_in_isolated_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = {
        "text": {
            "business_summary": "Analysis",
            "key_differences": "Differences",
            "investigation_progress": "No investigations",
            "next_steps": "Verify",
        },
        "citation_ids": ["report:fixed"],
        "gaps": [],
    }
    _child(
        tmp_path,
        monkeypatch,
        "assert os.environ['INVESTIGATION_TASK'] == 'analysis_report'\n"
        "assert not any(k in os.environ for k in ['MODEL_API_KEY', 'POSTGRES_PASSWORD'])\n"
        "assert sys.argv[sys.argv.index('--tools') + 1] == 'read_report_material'\n"
        "request('/assistant', [{'type':'toolCall','id':'one','name':'read_report_material','arguments':{}}])\n"
        "material = request('/read_report_material', {'id':'one','arguments':{}})\n"
        "assert material['summary']['count'] == 0\n"
        f"print({json.dumps(output)!r})\n",
    )
    assert runtime.run_pi_investigation(**_options()) == output
    _child(
        tmp_path,
        monkeypatch,
        "request('/assistant', [{'type':'toolCall','id':'one','name':'read_asset_history','arguments':{}}])\nprint('{}')\n",
    )
    with pytest.raises(ValueError, match="^tool_scope_denied$"):
        runtime.run_pi_investigation(**_options())


def test_report_reauthorizes_before_every_outbound_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[str] = []
    checks: list[int] = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers["Content-Length"]))
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

    def authorize() -> None:
        checks.append(1)
        if len(checks) == 2:
            raise ValueError("synthetic_material_denied")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _child(
        tmp_path,
        monkeypatch,
        "request('/chat/completions', {'model':'fixture'})\n"
        "request('/chat/completions', {'model':'fixture'})\nprint('{}')\n",
    )
    try:
        with pytest.raises(ValueError, match="^model_run_failed$"):
            runtime.run_pi_investigation(
                **_options(
                    before_model_call=authorize,
                    binding=SimpleNamespace(
                        endpoint=f"http://provider.invalid:{server.server_port}/v1",
                        resolved_address="127.0.0.1",
                        protocol="chat_completions",
                        model_identity="fixture",
                    ),
                )
            )
        assert checks == [1, 1]
        assert requests == ["/v1/chat/completions"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
