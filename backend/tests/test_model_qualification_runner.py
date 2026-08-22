import http.client
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from app.domain.model_qualification import model_binding
from app.model_qualification_runner import _start_provider_proxy


class _Provider(BaseHTTPRequestHandler):
    response_body = b'{"ok":true}'
    requests: list[tuple[str, str | None, bytes]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.requests.append(
            (self.path, self.headers.get("Authorization"), self.rfile.read(length))
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
    dns_calls: list[str] = []

    def resolve_internal(
        host: str, port: int | None, *args: Any, **kwargs: Any
    ) -> Any:
        if host == "model.internal":
            dns_calls.append(host)
            return original_getaddrinfo("127.0.0.1", port, *args, **kwargs)
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve_internal)
    binding = _binding(provider.server_port)
    dns_calls.clear()
    proxy, proxy_thread = _start_provider_proxy(binding)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", proxy.server_port)
        connection.request(
            "POST",
            "/chat/completions",
            body=b"fixture",
            headers={"Authorization": "Bearer test-secret"},
        )
        response = connection.getresponse()

        assert response.status == 200
        assert response.read() == _Provider.response_body
        assert dns_calls == []
        assert _Provider.requests[-1] == (
            "/v1/chat/completions",
            "Bearer test-secret",
            b"fixture",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        proxy_thread.join()
        provider.shutdown()
        provider.server_close()
        provider_thread.join()


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
