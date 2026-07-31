#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class CloudAtlasFixtureHandler(BaseHTTPRequestHandler):
    expected_token = ""
    log_path = Path("/tmp/cloudatlas-fixture.jsonl")

    def write_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
                "items": [
                    {"id": "fixture-asset-1", "ip": "192.0.2.10", "status": "valid"}
                ],
                "page": int(page),
                "size": int(query.get("size", ["1"])[0]),
                "total": 1,
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
    ThreadingHTTPServer(
        (args.bind, args.port), CloudAtlasFixtureHandler
    ).serve_forever()


if __name__ == "__main__":
    main()
