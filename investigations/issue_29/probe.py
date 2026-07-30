#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import http.client
import importlib.util
import io
import json
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
DEFAULT_DEMO_ROOT = HERE.parents[2] / "beijing-mobile-exposure-demo"
SERVICE_ID = "cloudatlas-read"
INSTANCE_ID = "cloudatlas-fixture"
CAPSET_ID = "cloudatlas-readonly"
METHOD = "cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets"
UPSTREAM_TOKEN = "fixture-upstream-token"
CAPSET_TOKEN = "fixture-capset-token"
CUSTOMER_HEADERS = [
    "序号",
    "资产IP",
    "起始端口",
    "结束端口",
    "是否web界面",
    "web界面url",
    "服务类型",
    "资产负责人",
    "资产所属部门",
    "端口负责人",
    "部门",
]
REQUIRED_CUSTOMER_HEADERS = {
    "资产IP",
    "起始端口",
    "结束端口",
    "是否web界面",
    "web界面url",
}


def run(
    command: list[str], *, input_text: str | None = None, timeout: int = 120
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        check=True,
        timeout=timeout,
    )


def wait_for_runtime(base_url: str) -> None:
    for _ in range(60):
        try:
            with urllib.request.urlopen(
                f"{base_url}/admin/v1/status", timeout=1
            ) as response:
                if response.status == 200:
                    return
        except OSError, urllib.error.URLError:
            time.sleep(0.25)
    raise RuntimeError("OctoBus runtime did not become ready")


def xlsx_bytes(headers: list[str]) -> bytes:
    rows = [
        headers,
        [
            "1",
            "192.0.2.10",
            "443",
            "443",
            "否",
            "",
            "https",
            "测试负责人",
            "测试部门",
            "",
            "",
        ],
    ]
    sheet_rows = []
    for row_number, row in enumerate(rows, start=1):
        cells = []
        for column_number, value in enumerate(row, start=1):
            column = ""
            number = column_number
            while number:
                number, remainder = divmod(number - 1, 26)
                column = chr(65 + remainder) + column
            cells.append(
                f'<c r="{column}{row_number}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        )
        workbook.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        workbook.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Assets" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        workbook.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{''.join(sheet_rows)}</sheetData></worksheet>",
        )
    return output.getvalue()


def fixture_has_required_headers(path: Path) -> bool:
    """Read the inline-string header format emitted by this investigation fixture."""
    try:
        with zipfile.ZipFile(path) as workbook:
            root = ElementTree.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
    except KeyError, ElementTree.ParseError, zipfile.BadZipFile:
        return False
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    first_row = root.find(".//x:sheetData/x:row", namespace)
    if first_row is None:
        return False
    headers = {
        text.text or ""
        for cell in first_row.findall("x:c", namespace)
        if (text := cell.find(".//x:t", namespace)) is not None
    }
    return REQUIRED_CUSTOMER_HEADERS <= headers


def upload(base_url: str, filename: str, body: bytes, token: str) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{base_url}/api/customer-files?filename={urllib.parse.quote(filename)}",
        data=body,
        headers={"Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def oversized_upload(base_url: str, filename: str, size: int, token: str) -> int:
    parsed = urllib.parse.urlparse(base_url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
    connection.putrequest(
        "POST", f"/api/customer-files?filename={urllib.parse.quote(filename)}"
    )
    connection.putheader("Authorization", f"Bearer {token}")
    connection.putheader("Content-Length", str(size))
    connection.endheaders()
    response = connection.getresponse()
    response.read()
    connection.close()
    return response.status


def run_demo_parser(demo_root: Path, guest_image: str, workbook: bytes) -> int:
    with tempfile.TemporaryDirectory(prefix="exposure-issue29-parser-") as directory:
        root = Path(directory)
        script = root / "tools/reconciliation/compare_customer_report.py"
        script.parent.mkdir(parents=True)
        shutil.copy2(
            demo_root / "tools/reconciliation/compare_customer_report.py", script
        )
        customer = root / "attachments/customer-fixture.xlsx"
        customer.parent.mkdir()
        customer.write_bytes(workbook)
        run_dir = root / "data/raw/cloudatlas/fixture-run"
        run_dir.mkdir(parents=True)
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "/usr/bin/python3",
                "--volume",
                f"{root}:/workspace",
                "--workdir",
                "/workspace",
                guest_image,
                "tools/reconciliation/compare_customer_report.py",
                "--customer",
                "attachments/customer-fixture.xlsx",
                "--run-dir",
                "data/raw/cloudatlas/fixture-run",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode


def probe_customer_upload(demo_root: Path, guest_image: str) -> dict:
    report_server_path = demo_root / "tools/report_server.py"
    spec = importlib.util.spec_from_file_location(
        "issue29_demo_report_server", report_server_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load demo report server")
    report_server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report_server)

    token = "fixture-upload-token"
    valid_workbook = xlsx_bytes(CUSTOMER_HEADERS)
    missing_structure = xlsx_bytes(["资产名称"])
    with tempfile.TemporaryDirectory(prefix="exposure-issue29-upload-") as directory:
        attachments = Path(directory) / "attachments"

        class Handler(report_server.ReportHandler):
            attachments_directory = attachments
            upload_token = token
            upload_max_bytes = report_server.ReportHandler.upload_max_bytes

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = report_server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            success_status, success = upload(
                base_url, "customer-fixture.xlsx", valid_workbook, token
            )
            assert success_status == 201, success
            assert success["sha256"] == hashlib.sha256(valid_workbook).hexdigest()
            accepted_after_success = len(list(attachments.iterdir()))

            duplicate_status, duplicate = upload(
                base_url, "customer-fixture.xlsx", valid_workbook, token
            )
            assert duplicate_status == 201, duplicate
            duplicate_creates_artifact = (
                len(list(attachments.iterdir())) == accepted_after_success + 1
            )

            rejected_start = len(list(attachments.iterdir()))
            unsupported_status, unsupported = upload(
                base_url, "customer-fixture.csv", b"fixture", token
            )
            malformed_status, malformed = upload(
                base_url, "customer-fixture.xlsx", b"not-a-workbook", token
            )
            oversized_status = oversized_upload(
                base_url,
                "customer-fixture.xlsx",
                Handler.upload_max_bytes + 1,
                token,
            )
            assert (unsupported_status, malformed_status, oversized_status) == (
                415,
                415,
                413,
            )
            assert len(list(attachments.iterdir())) == rejected_start
            rejected_errors = json.dumps([unsupported, malformed], ensure_ascii=False)
            assert "192.0.2.10" not in rejected_errors
            assert token not in rejected_errors

            missing_status, missing = upload(
                base_url, "missing-structure.xlsx", missing_structure, token
            )
            assert missing_status == 201, missing
            missing_structure_retained = (
                len(list(attachments.iterdir())) == rejected_start + 1
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    parser_status = run_demo_parser(demo_root, guest_image, valid_workbook)
    missing_parser_status = run_demo_parser(demo_root, guest_image, missing_structure)
    assert parser_status == 0

    with tempfile.TemporaryDirectory(
        prefix="exposure-issue29-validated-upload-"
    ) as directory:
        validated_attachments = Path(directory) / "attachments"

        class ValidatedHandler(report_server.ReportHandler):
            attachments_directory = validated_attachments
            upload_token = token
            upload_max_bytes = report_server.ReportHandler.upload_max_bytes

            @staticmethod
            def valid_excel(path: Path, suffix: str) -> bool:
                return (
                    suffix == ".xlsx"
                    and report_server.ReportHandler.valid_excel(path, suffix)
                    and fixture_has_required_headers(path)
                )

            def log_message(self, format: str, *args: object) -> None:
                pass

        validated_server = report_server.ThreadingHTTPServer(
            ("127.0.0.1", 0), ValidatedHandler
        )
        validated_thread = threading.Thread(
            target=validated_server.serve_forever, daemon=True
        )
        validated_thread.start()
        validated_base_url = f"http://127.0.0.1:{validated_server.server_address[1]}"
        try:
            validated_status, _ = upload(
                validated_base_url,
                "missing-structure.xlsx",
                missing_structure,
                token,
            )
            assert validated_status == 415
            assert not list(validated_attachments.iterdir())
        finally:
            validated_server.shutdown()
            validated_server.server_close()
            validated_thread.join(timeout=5)

    return {
        "success": {
            "http_status": success_status,
            "sha256_matches": True,
            "parser_exit": parser_status,
        },
        "max_bytes": Handler.upload_max_bytes,
        "rejections": {
            "unsupported": unsupported_status,
            "oversized": oversized_status,
            "malformed": malformed_status,
            "accepted_partial_artifacts": 0,
            "errors_redacted": True,
        },
        "current_gaps": {
            "duplicate_creates_artifact": duplicate_creates_artifact,
            "missing_structure_http_status": missing_status,
            "missing_structure_parser_exit": missing_parser_status,
            "missing_structure_retained": missing_structure_retained,
        },
        "candidate_structure_gate": {
            "missing_structure_http_status": validated_status,
            "accepted_partial_artifacts": 0,
        },
    }


def post_json(url: str, payload: dict, token: str) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read() or b"{}")


def source_fingerprint(payload: dict) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def fingerprint_material(base_url: str) -> tuple[dict, dict]:
    admin = f"{base_url}/admin/v1"
    service = get_json(f"{admin}/services/{SERVICE_ID}")
    instance = get_json(f"{admin}/instances/{INSTANCE_ID}")
    capset = get_json(f"{admin}/capsets/{CAPSET_ID}")
    instances = get_json(f"{admin}/capsets/{CAPSET_ID}/instances")["instances"]
    methods = get_json(f"{admin}/capsets/{CAPSET_ID}/methods")["methods"]
    tokens = get_json(f"{admin}/capsets/{CAPSET_ID}/tokens")["tokens"]
    material = {
        "schema": "exposure-agent.cloudatlas-source-fingerprint.v1",
        "service": {
            "id": service["ID"],
            "package_sha256": service["PackageSHA256"],
            "package_version": service["PackageVersion"],
            "descriptor_sha256": service["DescriptorSHA256"],
        },
        "instance": {
            "id": instance["ID"],
            "service_id": instance["ServiceID"],
            "config_sha256": instance["ConfigSHA256"],
            "secret_sha256": instance["SecretSHA256"],
        },
        "capset": {
            "id": capset["ID"],
            "enabled": capset["Enabled"],
            "token_bindings": sorted(
                [
                    {"id": item["ID"], "token_hash": item["TokenHash"]}
                    for item in tokens
                ],
                key=lambda item: item["id"],
            ),
            "instances": sorted(
                [
                    {
                        "service_id": item["ServiceID"],
                        "instance_id": item["InstanceID"],
                        "enabled": item["Enabled"],
                        "include_all_methods": item["IncludeAllMethods"],
                    }
                    for item in instances
                ],
                key=lambda item: (item["service_id"], item["instance_id"]),
            ),
            "methods": sorted(
                [
                    {"name": item["MethodFullName"], "enabled": item["Enabled"]}
                    for item in methods
                ],
                key=lambda item: item["name"],
            ),
        },
        "selected_method": METHOD,
    }
    return material, service


def demonstrate_fingerprint(base_url: str) -> tuple[dict, dict]:
    material, service = fingerprint_material(base_url)
    baseline = source_fingerprint(material)
    assert source_fingerprint(copy.deepcopy(material)) == baseline
    variants = {
        "instance_binding": ("instance", "id", "another-instance"),
        "config": ("instance", "config_sha256", "different-config-hash"),
        "credential": ("instance", "secret_sha256", "different-secret-hash"),
        "capset_authorization": (
            "capset",
            "token_bindings",
            [{"id": "probe", "token_hash": "rotated"}],
        ),
        "selected_method_contract": (
            None,
            "selected_method",
            "cloudatlas.read.v2.CloudAtlasReadService/ListIPAssets",
        ),
    }
    changed = []
    for name, (section, key, value) in variants.items():
        variant = copy.deepcopy(material)
        target = variant if section is None else variant[section]
        target[key] = value
        assert source_fingerprint(variant) != baseline, name
        changed.append(name)
    return {"stable": True, "invalidations": changed}, service


def octobus(container: str, *args: str, input_text: str | None = None) -> dict:
    command = [
        "docker",
        "exec",
        *(["-i"] if input_text is not None else []),
        "-e",
        "PATH=/app/tools/octobus/bin:/app/tools/octobus/runtime/node_modules/.bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        container,
        "octobus",
        "--addr",
        "127.0.0.1:9000",
        *args,
    ]
    result = run(command, input_text=input_text)
    return json.loads(result.stdout or "{}")


def probe_octobus(image: str) -> dict:
    container = f"exposure-issue29-{uuid.uuid4().hex[:12]}"
    started = False
    try:
        run(
            [
                "docker",
                "run",
                "--detach",
                "--rm",
                "--name",
                container,
                "--publish",
                "127.0.0.1::9000",
                "--env",
                f"FIXTURE_CLOUDATLAS_TOKEN={UPSTREAM_TOKEN}",
                "--env",
                "PATH=/app/tools/octobus/bin:/app/tools/octobus/runtime/node_modules/.bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "--volume",
                f"{HERE}:/investigation:ro",
                image,
                "sh",
                "-c",
                "python3 /investigation/fixture_upstream.py --port 18080 & "
                "exec /app/tools/octobus/runtime/node_modules/.bin/octobus serve "
                "--data-dir /tmp/octobus --addr 0.0.0.0:9000",
            ]
        )
        started = True
        port_output = run(["docker", "port", container, "9000/tcp"]).stdout.strip()
        base_url = f"http://127.0.0.1:{port_output.rsplit(':', 1)[1]}"
        wait_for_runtime(base_url)

        octobus(
            container,
            "service",
            "import",
            SERVICE_ID,
            "/investigation/cloudatlas-read-service",
        )
        octobus(
            container,
            "instance",
            "create",
            INSTANCE_ID,
            "--service",
            SERVICE_ID,
            "--config-json",
            json.dumps(
                {
                    "baseUrl": "http://127.0.0.1:18080/openapi/",
                    "spaceId": "fixture-space",
                }
            ),
            "--secret",
            "-",
            input_text=json.dumps({"token": UPSTREAM_TOKEN}),
        )
        octobus(
            container, "capset", "create", CAPSET_ID, "--name", "CloudAtlasReadOnly"
        )
        octobus(
            container,
            "capset",
            "add-instance",
            CAPSET_ID,
            INSTANCE_ID,
            "--no-all-methods",
        )
        octobus(
            container, "capset", "select-method", CAPSET_ID, INSTANCE_ID, f"/{METHOD}"
        )
        octobus(
            container,
            "capset",
            "add-token",
            CAPSET_ID,
            "probe",
            "--name",
            "Issue29Probe",
            "--token-stdin",
            input_text=CAPSET_TOKEN,
        )

        endpoint = f"{base_url}/capsets/{CAPSET_ID}/connect/{INSTANCE_ID}/{METHOD}"
        status, response = post_json(
            endpoint, {"status": "valid", "page": 1, "size": 1}, CAPSET_TOKEN
        )
        assert status == 200, response
        assert response == {
            "items": [{"id": "fixture-asset-1", "ip": "192.0.2.10", "status": "valid"}],
            "page": 1,
            "size": 1,
            "total": 1,
        }, response
        log = run(
            ["docker", "exec", container, "cat", "/tmp/cloudatlas-fixture.jsonl"]
        ).stdout
        requests = [json.loads(line) for line in log.splitlines() if line]
        assert requests[-1]["token_matches"] is True
        missing_auth_status, _ = post_json(
            endpoint, {"status": "valid", "page": 1, "size": 1}, ""
        )
        wrong_auth_status, _ = post_json(
            endpoint, {"status": "valid", "page": 1, "size": 1}, "wrong-token"
        )
        assert missing_auth_status == 401
        assert wrong_auth_status == 401

        failure_expectations = {
            "authentication": (
                91,
                401,
                "unauthenticated",
                "cloudatlas_authentication_failed",
            ),
            "authorization": (
                92,
                403,
                "permission_denied",
                "cloudatlas_authorization_failed",
            ),
            "upstream": (93, 503, "unavailable", "cloudatlas_upstream_failed"),
        }
        failures = {}
        for failure_name, expected in failure_expectations.items():
            page, expected_status, expected_code, expected_message = expected
            failure_status, failure = post_json(
                endpoint,
                {"status": "valid", "page": page, "size": 1},
                CAPSET_TOKEN,
            )
            assert (
                failure_status,
                failure.get("code"),
                failure.get("message"),
            ) == (expected_status, expected_code, expected_message), failure
            failures[failure_name] = {
                "http_status": failure_status,
                "category": failure["message"],
            }

        contract_status, contract_failure = post_json(
            endpoint,
            {"status": "valid", "page": 99, "size": 1},
            CAPSET_TOKEN,
        )
        assert contract_status == 500, contract_failure
        assert contract_failure.get("code") == "data_loss", contract_failure
        assert (
            contract_failure.get("message") == "cloudatlas_response_contract_failed"
        ), contract_failure
        connectivity_status, connectivity_failure = post_json(
            endpoint,
            {"status": "valid", "page": 98, "size": 1},
            CAPSET_TOKEN,
        )
        assert connectivity_status == 503, connectivity_failure
        assert (
            connectivity_failure.get("message") == "cloudatlas_connectivity_failed"
        ), connectivity_failure
        openapi = get_json(f"{base_url}/admin/v1/catalog/{CAPSET_ID}/openapi.json")
        expected_path = f"/capsets/{CAPSET_ID}/connect/{INSTANCE_ID}/{METHOD}"
        assert set(openapi["paths"]) == {expected_path}, openapi["paths"]
        temporary_configs = run(
            [
                "docker",
                "exec",
                container,
                "sh",
                "-c",
                "find /tmp -maxdepth 1 -type d -name 'cloudatlas-read-*' -print",
            ]
        ).stdout.splitlines()
        assert not temporary_configs
        fingerprint, service = demonstrate_fingerprint(base_url)
        return {
            "capset_auth": {"missing": missing_auth_status, "wrong": wrong_auth_status},
            "connect_status": status,
            "failures": failures,
            "fingerprint": fingerprint,
            "connectivity_failure": connectivity_failure["message"],
            "credential_handling": {"temporary_config_removed": True},
            "method": METHOD,
            "read_only_capset_paths": sorted(openapi["paths"]),
            "upstream_method": requests[-1]["method"],
            "upstream_path": requests[-1]["path"],
            "upstream_token_present": requests[-1]["token_present"],
            "service_package": {
                "version": service["PackageVersion"],
                "package_sha256": service["PackageSHA256"],
                "descriptor_sha256": service["DescriptorSHA256"],
            },
        }
    finally:
        if started:
            subprocess.run(
                ["docker", "rm", "--force", container],
                capture_output=True,
                text=True,
                timeout=15,
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--octobus-image", default="cloudatlas-octobus:local")
    parser.add_argument(
        "--demo-root",
        type=Path,
        default=DEFAULT_DEMO_ROOT,
    )
    parser.add_argument(
        "--guest-image", default="cloudatlas-reconcile-agent-compose-guest:local"
    )
    args = parser.parse_args()
    evidence = {
        "customer_upload": probe_customer_upload(
            args.demo_root.resolve(), args.guest_image
        ),
        "octobus": probe_octobus(args.octobus_image),
    }
    print(json.dumps(evidence, sort_keys=True))  # noqa: T201 - probe emits sanitized evidence


if __name__ == "__main__":
    main()
