"""Activate one local fixed-response model connection for the UX-04 chain."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


base = os.environ["CHAIN_API_URL"]


def request(path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=150) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        try:
            code = json.loads(error.read()).get("detail", {}).get("code", "unknown")
        except (UnicodeDecodeError, ValueError):
            code = "unknown"
        raise RuntimeError(f"{path} returned {error.code}: {code}") from None


login = urllib.request.Request(
    base + "/api/v1/login/access-token",
    data=urllib.parse.urlencode(
        {
            "username": os.environ["FIRST_SUPERUSER"],
            "password": os.environ["FIRST_SUPERUSER_PASSWORD"],
        }
    ).encode(),
)
with urllib.request.urlopen(login, timeout=30) as response:
    token = json.load(response)["access_token"]
auth = {"Authorization": "Bearer " + token}

_, listed = request("/api/v1/model-connections", headers=auth)
generation = listed["generation"]
_, created = request(
    "/api/v1/model-connections",
    {
        "expected_generation": generation,
        "name": "EXP-UX-04 local fixed workflow",
        "endpoint": "http://model-workflow-provider:8080/v1",
        "protocol": "chat_completions",
        "model_identity": os.environ["MODEL_WORKFLOW_PROVIDER_IDENTITY"],
        "api_key": os.environ["MODEL_WORKFLOW_PROVIDER_KEY"],
    },
    {**auth, "Idempotency-Key": "exp-ux-04-chain-save"},
)
connection = created["operation"]["connection_id"]
_, validated = request(
    f"/api/v1/model-connections/{connection}/validate",
    {"expected_generation": request("/api/v1/model-connections", headers=auth)[1]["generation"]},
    {**auth, "Idempotency-Key": "exp-ux-04-chain-validate"},
)
operation = validated["operation"]["id"]
deadline = time.monotonic() + 150
while time.monotonic() < deadline:
    _, current = request(f"/api/v1/model-connections/operations/{operation}", headers=auth)
    status = current["operation"]["status"]
    if status == "SUCCEEDED":
        break
    if status in {"FAILED", "UNKNOWN"}:
        raise RuntimeError("model validation " + status)
    time.sleep(0.3)
else:
    raise RuntimeError("model validation timed out")
_, activated = request(
    f"/api/v1/model-connections/{connection}/activate",
    {"expected_generation": request("/api/v1/model-connections", headers=auth)[1]["generation"]},
    {**auth, "Idempotency-Key": "exp-ux-04-chain-activate"},
)
if activated["state"]["active_id"] != connection:
    raise RuntimeError("model connection did not become active")

Path(os.environ["CHAIN_INPUT_PATH"]).write_text(
    json.dumps(
        {
            "ui": os.environ["CHAIN_UI_URL"],
            "api": base,
            "token": token,
            "workbook": os.environ["CHAIN_WORKBOOK_PATH"],
            "cloudatlas_capset_token": os.environ["CLOUDATLAS_CAPSET_TOKEN"],
            "output": os.environ["CHAIN_OUTPUT_PATH"],
            "create_published_run": True,
            "connection_version": connection,
        }
    )
)
