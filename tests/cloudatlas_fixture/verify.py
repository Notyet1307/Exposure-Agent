#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any

from app.domain.cloudatlas_sources import OctobusCloudAtlasClient
from app.domain.models import SourceInstance

SERVICE_ID = "cloudatlas-read"
INSTANCE_ID = "cloudatlas-fixture"
CAPSET_ID = "cloudatlas-readonly"
METHOD = "cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets"
CAPSET_TOKEN = "fixture-capset-token"
PACKAGE_SHA256 = "882a197f630497f00307be613f7c361a32dad156092726e35b2ce9855c0617e9"
DESCRIPTOR_SHA256 = "3fada7cb00f3bca132c28d316ea61158522a1a07d3e80a83f9e68010d1a588e0"


def get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:
        payload = json.loads(response.read() or b"{}")
    assert isinstance(payload, dict)
    return payload


def post_json(
    url: str, body: dict[str, Any], token: str | None
) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read() or b"{}")
            return response.status, payload
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:19000")
    parser.add_argument("--print-backend-fingerprint", action="store_true")
    parser.add_argument("--stored-fingerprint")
    parser.add_argument(
        "--expected-validation-status", choices=("validated", "invalid")
    )
    args = parser.parse_args()
    if (args.stored_fingerprint is None) != (
        args.expected_validation_status is None
    ):
        parser.error(
            "--stored-fingerprint and --expected-validation-status must be used together"
        )
    base_url = args.base_url.rstrip("/")
    service = get_json(f"{base_url}/admin/v1/services/{SERVICE_ID}")
    assert service["PackageSHA256"] == PACKAGE_SHA256
    assert service["DescriptorSHA256"] == DESCRIPTOR_SHA256
    assert [method["full_name"] for method in service["Methods"]] == [METHOD]

    endpoint = (
        f"{base_url}/capsets/{CAPSET_ID}/connect/{INSTANCE_ID}/{METHOD}"
    )
    status, payload = post_json(
        endpoint, {"status": "valid", "page": 1, "size": 1}, CAPSET_TOKEN
    )
    assert status == 200
    assert payload == {
        "items": [
            {"id": "fixture-asset-1", "ip": "192.0.2.10", "status": "valid"}
        ],
        "page": 1,
        "size": 1,
        "total": 1,
    }

    openapi = get_json(f"{base_url}/admin/v1/catalog/{CAPSET_ID}/openapi.json")
    assert set(openapi["paths"]) == {
        f"/capsets/{CAPSET_ID}/connect/{INSTANCE_ID}/{METHOD}"
    }

    missing_status, missing_body = post_json(
        endpoint, {"status": "valid", "page": 1, "size": 1}, None
    )
    wrong_status, wrong_body = post_json(
        endpoint,
        {"status": "valid", "page": 1, "size": 1},
        "wrong-capset-token",
    )
    assert missing_status == wrong_status == 401
    assert missing_body.get("code") == wrong_body.get("code") == "unauthenticated"
    assert "capset token is required" in str(missing_body.get("message"))
    assert "capset token is required" in str(wrong_body.get("message"))
    failures = {
        91: (401, "unauthenticated", "cloudatlas_authentication_failed"),
        92: (403, "permission_denied", "cloudatlas_authorization_failed"),
        93: (503, "unavailable", "cloudatlas_upstream_failed"),
        98: (503, "unavailable", "cloudatlas_connectivity_failed"),
        99: (500, "data_loss", "cloudatlas_response_contract_failed"),
    }
    failure_bodies: list[dict[str, Any]] = [missing_body, wrong_body]
    for page, expected in failures.items():
        failure_status, failure_body = post_json(
            endpoint,
            {"status": "valid", "page": page, "size": 1},
            CAPSET_TOKEN,
        )
        assert (
            failure_status,
            failure_body.get("code"),
            failure_body.get("message"),
        ) == expected
        failure_bodies.append(failure_body)

    serialized_failures = json.dumps(failure_bodies)
    for forbidden in (
        CAPSET_TOKEN,
        "fixture-upstream-token",
        "192.0.2.10",
        "TOKEN",
        "stderr",
    ):
        assert forbidden not in serialized_failures

    source = SourceInstance(
        project_id=uuid.uuid4(),
        instance_id=INSTANCE_ID,
        capset_id=CAPSET_ID,
        validated_fingerprint=args.stored_fingerprint,
    )
    if args.stored_fingerprint is None:
        fingerprint = OctobusCloudAtlasClient().validate_read(
            source, capset_token=CAPSET_TOKEN
        )
        if args.print_backend_fingerprint:
            sys.stdout.write(f"{fingerprint.value}\n")
    else:
        current = OctobusCloudAtlasClient().current_fingerprint(source)
        assert (current.value == args.stored_fingerprint) == (
            args.expected_validation_status == "validated"
        )


if __name__ == "__main__":
    main()
