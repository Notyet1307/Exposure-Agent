import http.client
import json
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import app.model_qualification_runner as runner
from app.domain.model_qualification import model_binding, qualification_prompt
from app.model_qualification_runner import _run_qualification, _start_provider_proxy


class _Provider(BaseHTTPRequestHandler):
    response_body = b'{"ok":true}'
    requests: list[
        tuple[str, str | None, str | None, str | None, str | None, bytes]
    ] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.requests.append(
            (
                self.path,
                self.headers.get("Authorization"),
                self.headers.get("Content-Type"),
                self.headers.get("Cookie"),
                self.headers.get("X-Qualification-Test"),
                self.rfile.read(length),
            )
        )
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.response_body)))
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, format: str, *args: object) -> None:
        return


def _binding(port: int) -> Any:
    return model_binding(
        endpoint=f"http://model.internal:{port}/v1",
        model_identity="fake-model",
        protocol="chat_completions",
        config_revision="test-v1",
        runner_build_version="runner-v1",
        agent_compose_runtime_version="compose-v1",
    )


def _loopback_binding() -> Any:
    return model_binding(
        endpoint="http://127.0.0.1:1/v1",
        model_identity="fake-model",
        protocol="chat_completions",
        config_revision="test-v1",
        runner_build_version="runner-v1",
        agent_compose_runtime_version="compose-v1",
    )


def test_proxy_pins_the_address_validated_by_model_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ThreadingHTTPServer(("127.0.0.1", 0), _Provider)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    original_getaddrinfo = socket.getaddrinfo
    model_dns_calls = 0

    def resolve_internal(
        host: str, port: int | None, *args: Any, **kwargs: Any
    ) -> Any:
        nonlocal model_dns_calls
        if host == "model.internal":
            model_dns_calls += 1
            rebound_address = (
                "127.0.0.1" if model_dns_calls == 1 else "169.254.169.254"
            )
            return original_getaddrinfo(rebound_address, port, *args, **kwargs)
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve_internal)
    binding = _binding(provider.server_port)
    proxy, proxy_thread = _start_provider_proxy(binding)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", proxy.server_port)
        connection.request(
            "POST",
            "/chat/completions",
            body=b"fixture",
            headers={
                "Authorization": "Bearer test-secret",
                "Content-Type": "application/json",
                "Cookie": "must-not-pass=customer-data",
                "X-Qualification-Test": "must-not-pass",
            },
        )
        response = connection.getresponse()

        assert response.status == 200
        assert response.read() == _Provider.response_body
        assert model_dns_calls == 1
        assert _Provider.requests[-1] == (
            "/v1/chat/completions",
            "Bearer test-secret",
            "application/json",
            None,
            None,
            b"fixture",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        proxy_thread.join()
        provider.shutdown()
        provider.server_close()
        provider_thread.join()


def test_qualification_prompt_uses_private_stdin_not_process_argv(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    binding = model_binding(
        endpoint="http://127.0.0.1:1/v1",
        model_identity="fake-model",
        protocol="chat_completions",
        config_revision="test-v1",
        runner_build_version="runner-v1",
        agent_compose_runtime_version="compose-v1",
    )
    invocation: dict[str, Any] = {}

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        invocation.update(args=args, **kwargs)
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="provider failed")

    monkeypatch.setattr("app.model_qualification_runner.subprocess.run", run)

    assert _run_qualification(binding, "test-secret", 1) == 0

    argv = invocation["args"]
    assert qualification_prompt() not in argv
    assert invocation["input"] == qualification_prompt()
    assert "test-secret" not in " ".join(argv)
    assert "test-secret" not in capsys.readouterr().out


def test_proxy_rejects_invalid_paths_and_oversized_requests() -> None:
    proxy, proxy_thread = _start_provider_proxy(_loopback_binding())
    try:
        for path, body, expected_status in (
            ("/unknown", b"fixture", 404),
            ("/chat/completions?fallback=external", b"fixture", 404),
            ("/chat/completions", b"x" * 1_000_001, 413),
        ):
            connection = http.client.HTTPConnection("127.0.0.1", proxy.server_port)
            if expected_status == 413:
                connection.putrequest("POST", path)
                connection.putheader("Content-Length", str(len(body)))
                connection.endheaders()
            else:
                connection.request("POST", path, body=body)
            response = connection.getresponse()
            assert response.status == expected_status
            response.read()
            connection.close()
    finally:
        proxy.shutdown()
        proxy.server_close()
        proxy_thread.join()


def test_runner_main_validates_configuration_and_cleans_up_proxy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    build_version = tmp_path / "runner-build-version"
    build_version.write_text("runner-v1\n", encoding="utf-8")
    for name, value in {
        "LLM_API_KEY": "test-secret",
        "LLM_API_ENDPOINT": "http://127.0.0.1:1/v1",
        "MODEL_IDENTITY": "fake-model",
        "LLM_API_PROTOCOL": "chat_completions",
        "MODEL_CONFIG_REVISION": "test-v1",
        "RUNNER_BUILD_VERSION_PATH": str(build_version),
        "AGENT_COMPOSE_RUNTIME_VERSION": "compose-v1",
    }.items():
        monkeypatch.setenv(name, value)

    events: list[str] = []

    class Server:
        server_port = 1234

        def shutdown(self) -> None:
            events.append("shutdown")

        def server_close(self) -> None:
            events.append("close")

    class Thread:
        def join(self) -> None:
            events.append("join")

    monkeypatch.setattr(
        runner, "_start_provider_proxy", lambda _binding: (Server(), Thread())
    )

    def run_qualification(binding: Any, api_key: str, proxy_port: int) -> int:
        events.append(f"run:{binding.model_identity}:{api_key}:{proxy_port}")
        return 0

    monkeypatch.setattr(runner, "_run_qualification", run_qualification)

    assert runner.main() == 0
    assert events == ["run:fake-model:test-secret:1234", "shutdown", "close", "join"]


def test_runner_main_fails_closed_for_missing_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    assert runner.main() == 1
    assert capsys.readouterr().err == (
        "model qualification runner: FAIL (llm_api_key_missing)\n"
    )


def test_runner_main_fails_closed_when_build_version_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    for name, value in {
        "LLM_API_KEY": "test-secret",
        "LLM_API_ENDPOINT": "http://127.0.0.1:1/v1",
        "MODEL_IDENTITY": "fake-model",
        "LLM_API_PROTOCOL": "chat_completions",
        "MODEL_CONFIG_REVISION": "test-v1",
        "RUNNER_BUILD_VERSION_PATH": str(tmp_path / "missing"),
    }.items():
        monkeypatch.setenv(name, value)

    assert runner.main() == 1
    assert capsys.readouterr().err == (
        "model qualification runner: FAIL (runtime_version_unavailable)\n"
    )


def test_runner_rejects_an_empty_build_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    build_version = tmp_path / "runner-build-version"
    build_version.write_text(" \n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version))

    with pytest.raises(ValueError, match="model_configuration_invalid"):
        runner._runner_build_version()


@pytest.mark.parametrize("failure", ["timeout", "invalid-output"])
def test_runner_emits_redacted_fail_closed_result_for_model_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    binding = _loopback_binding()

    def run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, 1)
        return subprocess.CompletedProcess(
            args, 0, stdout="not-json", stderr="raw-event"
        )

    monkeypatch.setattr("app.model_qualification_runner.subprocess.run", run)

    assert _run_qualification(binding, "test-secret", 1) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "FAIL"
    assert result["failure_code"] == (
        "model_run_failed" if failure == "timeout" else "model_output_invalid"
    )
    assert "test-secret" not in json.dumps(result)
    assert "raw-event" not in json.dumps(result)


def test_proxy_rejects_an_oversized_streamed_provider_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ThreadingHTTPServer(("127.0.0.1", 0), _Provider)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    original_getaddrinfo = socket.getaddrinfo

    def resolve_internal(
        host: str, port: int | None, *args: Any, **kwargs: Any
    ) -> Any:
        if host == "model.internal":
            return original_getaddrinfo("127.0.0.1", port, *args, **kwargs)
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve_internal)
    monkeypatch.setattr(_Provider, "response_body", b"x" * 1_000_001)
    proxy, proxy_thread = _start_provider_proxy(_binding(provider.server_port))
    try:
        connection = http.client.HTTPConnection("127.0.0.1", proxy.server_port)
        connection.request("POST", "/chat/completions", body=b"fixture")
        response = connection.getresponse()

        assert response.status == 502
    finally:
        proxy.shutdown()
        proxy.server_close()
        proxy_thread.join()
        provider.shutdown()
        provider.server_close()
        provider_thread.join()
