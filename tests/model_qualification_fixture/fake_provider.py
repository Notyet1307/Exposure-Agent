#!/usr/bin/env python3
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ACTIONS = (
    "CONFIRM_ASSET_OWNER",
    "ADD_AUTHENTICATED_SCAN",
    "VERIFY_NETWORK_ROUTE",
    "CONFIRM_SERVICE_EXPOSURE",
)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(204 if self.path == "/health" else 404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        checks = (
            self.path == "/v1/chat/completions",
            self.headers.get("Authorization")
            == f"Bearer {os.environ['MODEL_API_KEY']}",
            payload.get("model") == "fixture-model",
            "fixture-finding-1" in json.dumps(payload),
        )
        if not all(checks):
            print(
                f"qualification request rejected: {checks}",
                file=sys.stderr,
                flush=True,
            )
            self.send_error(400)
            return
        print("qualification request accepted", file=sys.stderr, flush=True)
        output = json.dumps(
            {
                "recommendations": [
                    {
                        "finding_id": f"fixture-finding-{number}",
                        "action_code": action,
                        "claims": [
                            {
                                "claim_id": f"fixture-claim-{number}",
                                "evidence_ids": [f"fixture-evidence-{number}"],
                            }
                        ],
                        "finding_modified": False,
                    }
                    for number, action in enumerate(ACTIONS, start=1)
                ],
                "unsupported_claims": [],
                "unauthorized_side_effects": [],
            },
            separators=(",", ":"),
        )
        events = (
            {
                "id": "fixture-response",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": output},
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "fixture-response",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
        )
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        body += "data: [DONE]\n\n"
        encoded = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
