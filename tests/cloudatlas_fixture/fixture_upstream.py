#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


class CloudAtlasFixtureHandler(BaseHTTPRequestHandler):
    expected_token = ""
    log_path = Path("/tmp/cloudatlas-fixture.jsonl")
    agent_compose_url = "http://agent-compose:7410"
    fail_next_read = False
    miss_next_session_query = False
    remove_session_after_get = False

    def write_raw(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_json(self, status: int, payload: dict) -> None:
        self.write_raw(
            status,
            json.dumps(payload, separators=(",", ":")).encode(),
            "application/json",
        )

    def proxy_agent_compose(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        if (
            self.path == "/agentcompose.v2.SandboxService/GetSandbox"
            and type(self).miss_next_session_query
        ):
            type(self).miss_next_session_query = False
            self.write_json(HTTPStatus.NOT_FOUND, {"code": "not_found"})
            return
        headers = {
            name: value
            for name in (
                "Authorization",
                "Connect-Protocol-Version",
                "Content-Type",
            )
            if (value := self.headers.get(name)) is not None
        }
        request = Request(
            f"{self.agent_compose_url}{self.path}",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request) as response:
                status = response.status
                response_body = response.read()
                content_type = response.headers.get(
                    "Content-Type", "application/json"
                )
        except HTTPError as error:
            status = error.code
            response_body = error.read()
            content_type = error.headers.get("Content-Type", "application/json")
        if (
            self.path == "/agentcompose.v2.SandboxService/GetSandbox"
            and type(self).remove_session_after_get
            and status == HTTPStatus.OK
        ):
            type(self).remove_session_after_get = False
            session_id = json.loads(body)["sandboxId"]
            remove_request = Request(
                f"{self.agent_compose_url}/agentcompose.v2.SandboxService/RemoveSandbox",
                data=json.dumps({"sandboxId": session_id}).encode(),
                headers=headers,
                method="POST",
            )
            with urlopen(remove_request):
                pass
        self.write_raw(status, response_body, content_type)

    def do_POST(self) -> None:
        if self.path.startswith("/agentcompose.v2."):
            self.proxy_agent_compose()
            return
        if self.path == "/fixture/fail-next":
            type(self).fail_next_read = True
        elif self.path == "/fixture/miss-next-session-query":
            type(self).miss_next_session_query = True
        elif self.path == "/fixture/remove-session-after-get":
            type(self).remove_session_after_get = True
        else:
            self.write_json(404, {"error": "not_found"})
            return
        self.write_json(200, {"armed": True})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        token = self.headers.get("TOKEN", "")
        with self.log_path.open("a", encoding="utf-8") as log:
            log.write(
                json.dumps(
                    {
                        "method": "GET",
                        "path": parsed.path,
                        "query": dict(sorted(query.items())),
                        "token_present": bool(token),
                        "token_matches": token == self.expected_token,
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
        if parsed.path != "/openapi/v1/asset/ip":
            self.write_json(404, {"error": "not_found"})
            return
        if token != self.expected_token:
            self.write_json(401, {"error": "authentication_failed"})
            return
        if type(self).fail_next_read:
            type(self).fail_next_read = False
            self.write_json(503, {"error": "fixture_failure"})
            return
        page = query.get("page", ["1"])[0]
        if page == "91":
            self.write_json(401, {"error": "authentication_failed"})
            return
        if page == "92":
            self.write_json(403, {"error": "authorization_failed"})
            return
        if page == "93":
            self.write_json(503, {"error": "upstream_unavailable"})
            return
        if page == "99":
            self.write_json(200, {"unexpected": True})
            return
        if page == "98":
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        self.write_json(
            200,
            {
                "code": 200,
                "data": {
                    "current": int(page),
                    "items": [
                        {"id": 1, "ip": "192.0.2.10", "status": "valid"}
                    ],
                    "size": int(query.get("size", ["1"])[0]),
                    "total": 1,
                },
                "message": "",
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument(
        "--log", type=Path, default=Path("/tmp/cloudatlas-fixture.jsonl")
    )
    args = parser.parse_args()
    CloudAtlasFixtureHandler.expected_token = os.environ["FIXTURE_CLOUDATLAS_TOKEN"]
    CloudAtlasFixtureHandler.log_path = args.log
    CloudAtlasFixtureHandler.agent_compose_url = os.environ.get(
        "FIXTURE_AGENT_COMPOSE_URL", "http://agent-compose:7410"
    ).rstrip("/")
    ThreadingHTTPServer(
        (args.bind, args.port), CloudAtlasFixtureHandler
    ).serve_forever()


if __name__ == "__main__":
    main()
