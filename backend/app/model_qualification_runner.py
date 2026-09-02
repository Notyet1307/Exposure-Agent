from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.domain.model_qualification import (
    ModelBinding,
    ModelQualificationOutput,
    _failed_evaluation,
    evaluate_qualification,
    model_binding,
    qualification_prompt,
    qualification_run_result_json,
)


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name.lower()}_missing")
    return value


def _runner_build_version() -> str:
    path = Path(
        os.environ.get("RUNNER_BUILD_VERSION_PATH", "/app/runner-build-version")
    )
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError("model_configuration_invalid")
    return value


def _start_provider_proxy(
    binding: ModelBinding,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    target_path = (
        "/responses" if binding.protocol == "responses" else "/chat/completions"
    )
    endpoint = urlsplit(binding.endpoint)
    address = (
        f"[{binding.resolved_address}]"
        if ":" in binding.resolved_address
        else binding.resolved_address
    )
    authority = address + (f":{endpoint.port}" if endpoint.port else "")
    pinned_endpoint = urlunsplit(
        (endpoint.scheme, authority, endpoint.path.rstrip("/"), "", "")
    )
    provider_host = endpoint.netloc

    class ProviderProxy(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            if parsed.path != target_path or parsed.query:
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1_000_000:
                self.send_error(413)
                return
            request_body = self.rfile.read(length)
            headers = {
                name: value
                for name, value in self.headers.items()
                if name.lower() in {"authorization", "content-type"}
            }
            headers["Host"] = provider_host
            try:
                with httpx.Client(
                    follow_redirects=False, timeout=120, trust_env=False
                ) as client:
                    with client.stream(
                        "POST",
                        pinned_endpoint + target_path,
                        headers=headers,
                        content=request_body,
                        extensions={"sni_hostname": endpoint.hostname},
                    ) as response:
                        if response.is_redirect:
                            self.send_error(502)
                            return
                        response_body = bytearray()
                        for chunk in response.iter_bytes():
                            response_body.extend(chunk)
                            if len(response_body) > 1_000_000:
                                self.send_error(502)
                                return
                        status_code = response.status_code
                        content_type = response.headers.get("Content-Type")
            except httpx.HTTPError:
                self.send_error(502)
                return
            self.send_response(status_code)
            if content_type:
                self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), ProviderProxy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def start_pinned_provider_proxy(
    binding: ModelBinding,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start the only Provider egress path, pinned to the qualified address."""
    return _start_provider_proxy(binding)


def stop_pinned_provider_proxy(
    proxy: ThreadingHTTPServer, proxy_thread: threading.Thread
) -> None:
    """Close every local proxy resource even if an earlier cleanup step fails."""
    try:
        proxy.shutdown()
    finally:
        try:
            proxy.server_close()
        finally:
            proxy_thread.join()


def main() -> int:
    try:
        api_key = _required_environment("LLM_API_KEY")
        binding = model_binding(
            endpoint=_required_environment("LLM_API_ENDPOINT"),
            model_identity=_required_environment("MODEL_IDENTITY"),
            protocol=_required_environment("LLM_API_PROTOCOL"),
            config_revision=_required_environment("MODEL_CONFIG_REVISION"),
            runner_build_version=_runner_build_version(),
            agent_compose_runtime_version=_required_environment(
                "AGENT_COMPOSE_RUNTIME_VERSION"
            ),
        )
    except OSError:
        sys.stderr.write(
            "model qualification runner: FAIL (runtime_version_unavailable)\n"
        )
        return 1
    except ValueError as error:
        sys.stderr.write(f"model qualification runner: FAIL ({error})\n")
        return 1

    proxy, proxy_thread = start_pinned_provider_proxy(binding)
    try:
        return _run_qualification(binding, api_key, proxy.server_port)
    finally:
        stop_pinned_provider_proxy(proxy, proxy_thread)


def _run_qualification(binding: ModelBinding, api_key: str, proxy_port: int) -> int:
    with tempfile.TemporaryDirectory(prefix="model-qualification-") as temporary:
        config_dir = Path(temporary) / "agent"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            '{"retry":{"enabled":false,"provider":{"maxRetries":0}}}',
            encoding="utf-8",
        )
        (config_dir / "models.json").write_text(
            json.dumps(
                {
                    "providers": {
                        "customer": {
                            "baseUrl": f"http://127.0.0.1:{proxy_port}",
                            "api": (
                                "openai-responses"
                                if binding.protocol == "responses"
                                else "openai-completions"
                            ),
                            "apiKey": "$MODEL_API_KEY",
                            "models": [{"id": binding.model_identity}],
                        }
                    }
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        environment = {
            "HOME": temporary,
            "LANG": "C.UTF-8",
            "MODEL_API_KEY": api_key,
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PI_CODING_AGENT_DIR": str(config_dir),
            "PI_OFFLINE": "1",
            "PI_SKIP_VERSION_CHECK": "1",
            "PI_TELEMETRY": "0",
        }
        try:
            completed = subprocess.run(
                [
                    "pi",
                    "--print",
                    "--no-session",
                    "--no-tools",
                    "--no-extensions",
                    "--no-skills",
                    "--no-prompt-templates",
                    "--no-themes",
                    "--no-context-files",
                    "--no-approve",
                    "--provider",
                    "customer",
                    "--model",
                    binding.model_identity,
                ],
                cwd=temporary,
                env=environment,
                input=qualification_prompt(),
                capture_output=True,
                text=True,
                timeout=float(
                    os.environ.get("MODEL_QUALIFICATION_TIMEOUT_SECONDS", "120")
                ),
            )
        except (OSError, subprocess.TimeoutExpired, ValueError):
            evaluation = _failed_evaluation("model_run_failed")
        else:
            if completed.returncode:
                evaluation = _failed_evaluation("model_run_failed")
            else:
                try:
                    output = ModelQualificationOutput.model_validate_json(
                        completed.stdout.strip()
                    )
                except ValueError:
                    evaluation = _failed_evaluation("model_output_invalid")
                else:
                    evaluation = evaluate_qualification(output)

    sys.stdout.write(
        qualification_run_result_json(binding=binding, evaluation=evaluation) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
