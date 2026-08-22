import http.client
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

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
