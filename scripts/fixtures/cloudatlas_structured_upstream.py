#!/usr/bin/env python3
"""Private synthetic HTTPS source. Only scenario names and page counts are logged."""

from __future__ import annotations

import json
import os
import ssl
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path("/fixture-state")
CONTRACTS = json.loads(Path("/contract.json").read_text())["domains"]
PATHS = {"/openapi" + v["path"]: (k, v) for k, v in CONTRACTS.items()}


def sample(shape, key=""):
    if "enum" in shape:
        return shape["enum"][0]
    kind = shape["type"]
    if kind == "identity":
        return 900719925474099312345
    if kind == "integer":
        return 443 if key == "port" else 0
    if kind == "boolean":
        return key == "enable"
    if kind == "string":
        return (
            "valid"
            if key == "status"
            else "2001:db8::7"
            if key == "ip"
            else "2026-10-03 00:00:00"
            if key.endswith("_at")
            else f"Synthetic {key}%_\\\0text <img src=https://never-fetch.example/x>"
        )
    if kind == "array":
        return [sample(shape["items"])]
    return {key: sample(value, key) for key, value in shape["properties"].items()}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        parsed = urlsplit(self.path)
        if (
            parsed.path not in PATHS
            or self.headers.get("TOKEN") != os.environ["FIXTURE_CLOUDATLAS_TOKEN"]
        ):
            self.send_response(403)
            self.end_headers()
            return
        domain, contract = PATHS[parsed.path]
        query = parse_qs(parsed.query)
        page, size = int(query.get("page", ["0"])[0]), int(query.get("size", ["0"])[0])
        expected = {
            "space": ["281"],
            "page": [str(page)],
            "size": [str(size)],
            "sort": ["-id"],
            **{key: [str(value)] for key, value in contract["filters"].items()},
        }
        state = json.loads((ROOT / "control.json").read_text())
        mode = state["mode"]
        assert query == expected and 1 <= size <= 200 and page >= 1
        with (ROOT / "requests.jsonl").open("a") as out:
            out.write(
                json.dumps({"domain": domain, "mode": mode, "page": page, "size": size})
                + "\n"
            )
        if (
            mode in ("unauthorized", "forbidden", "redirect")
            or mode == "page2_failure"
            and page == 2
        ):
            self.send_response(
                {"unauthorized": 401, "forbidden": 403, "redirect": 302}.get(mode, 502)
            )
            if mode == "redirect":
                self.send_header("Location", "https://never-follow.example/")
            self.end_headers()
            return
        if mode in ("timeout", "unknown_recovery"):
            time.sleep(2)
        total = 0 if mode == "empty" else 2
        if mode == "total_drift" and page == 2:
            total = 3
        rows = []
        for index in range((page - 1) * size, min(page * size, total)):
            row = sample(contract["schema"])
            row["id"] = 900719925474099312345 + (0 if mode == "duplicate" else index)
            row["unknown_private_fixture_field"] = "never saved"
            if domain == "crawler":
                row.update(
                    headers="private header excluded", data="private body excluded"
                )
            if domain == "dir":
                row["icon_url"] = None
                row["render_title"] = None
                row["ip_info"] = {}
            if domain == "seed_icon":
                row["icon_url"] = None
            if mode == "type_conflict":
                row["id"] = "not-an-integer"
            rows.append(row)
        raw = json.dumps(
            {
                "code": 200,
                "message": "ok",
                "data": {"current": page, "size": size, "total": total, "items": rows},
            },
            ensure_ascii=False,
        ).encode()
        if mode == "byte_limit":
            raw = b"x" * 131073
        elif mode == "invalid_utf8":
            raw = b"\xff"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if mode == "compressed":
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8443), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain("/tls/cert.pem", "/tls/key.pem")
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    server.serve_forever()
