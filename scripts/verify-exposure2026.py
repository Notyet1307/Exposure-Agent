#!/usr/bin/env python3
"""Isolated synthetic API and real-browser pilot. No production config, Docker, or external calls."""
import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

EXPECTED_REQUIRED_HEADERS = (
    "资产IP",
    "起始端口",
    "结束端口",
    "是否web界面",
    "web界面url",
)
VALID_FILENAME = "customer-ledger-valid.xlsx"
INVALID_HEADER_FILENAME = "customer-ledger-missing-header.xlsx"
INVALID_PORT_FILENAME = "customer-ledger-port-70000.xlsx"


class Blocked(Exception):
    pass


def require(value, message):
    if not value:
        raise AssertionError(message)


def classify(fn):
    try:
        fn()
        return "PASS", ""
    except Blocked as exc:
        return "BLOCKED", str(exc)
    except Exception as exc:
        return "FAIL", f"{type(exc).__name__}: {exc}"


def sha256_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def doctor(repo, pg):
    py = repo / ".venv/bin/python"
    for path in (py, pg / "postgres", pg / "createdb", pg / "initdb", pg / "pg_ctl", pg / "psql"):
        if not path.is_file():
            raise Blocked(f"Missing runtime: {path}")
    expected = py.resolve()
    current = Path(sys.executable).resolve()
    if current != expected:
        raise Blocked(
            f"Run this helper with the project interpreter {py} (resolved {expected}); "
            f"current interpreter is {current} (Python {sys.version.split()[0]})."
        )
    if "filter" not in inspect.signature(tarfile.TarFile.extract).parameters:
        raise Blocked(
            f"Python {sys.version.split()[0]} cannot extract tar archives with tarfile filter; "
            f"use {expected}."
        )
    try:
        subprocess.run(
            [str(py), "-c", "import fastapi,uvicorn,sqlmodel,psycopg,alembic,openpyxl"],
            check=True,
            env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Blocked("Backend interpreter or required imports unavailable") from exc
    return py


def source_state(repo):
    raw = subprocess.check_output(
        ["git", "-C", str(repo), "status", "--porcelain=v1", "-z", "--untracked-files=all"]
    )
    entries = [item.decode() for item in raw.split(b"\0") if item]
    forbidden = [
        item
        for item in entries
        if not (
            item[3:] in ("scripts/verify-exposure2026.py", "scripts/verify-exposure2026-ui.cjs")
            or item[3:].startswith(".claude/skills/verify-exposure2026/")
        )
    ]
    if forbidden:
        raise Blocked("Product working tree differs from committed HEAD: " + repr(forbidden))
    return entries


def stop_group(pgid, child=None):
    # Only call for groups explicitly created by this supervisor or its browser child.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        for _ in range(30):
            if child is not None:
                child.poll()  # Reap our direct child before checking its group.
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                return False
            time.sleep(0.1)
    return False


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def write_xlsx(path, headers, rows):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()


def ledger_fixtures(root, required_headers):
    headers = list(required_headers)
    if (
        len(headers) != len(EXPECTED_REQUIRED_HEADERS)
        or set(headers) != set(EXPECTED_REQUIRED_HEADERS)
    ):
        raise Blocked(
            "Actual upload profile required_headers differ from the synthetic ledger schema: "
            f"{headers}"
        )

    def row_values(ip, start=443, end=443, web="否", url=None):
        return {
            "资产IP": ip,
            "起始端口": start,
            "结束端口": end,
            "是否web界面": web,
            "web界面url": url,
        }

    def project(values, columns):
        return [values[column] for column in columns]

    fixtures = root / "fixtures"
    fixtures.mkdir()
    valid = fixtures / VALID_FILENAME
    write_xlsx(
        valid,
        headers,
        [project(row_values("192.0.2.10"), headers), project(row_values("192.0.2.11"), headers)],
    )
    missing_headers = [header for header in headers if header != "web界面url"]
    missing = fixtures / INVALID_HEADER_FILENAME
    write_xlsx(missing, missing_headers, [project(row_values("192.0.2.12"), missing_headers)])
    invalid_port = fixtures / INVALID_PORT_FILENAME
    write_xlsx(invalid_port, headers, [project(row_values("192.0.2.13", start=70000, end=70000), headers)])
    return {
        "valid": {
            "path": str(valid),
            "file": VALID_FILENAME,
            "sha256": sha256_file(valid),
            "headers": headers,
            "record_count": 2,
            "ips": ["192.0.2.10", "192.0.2.11"],
        },
        "invalid_header": {
            "path": str(missing),
            "file": INVALID_HEADER_FILENAME,
            "sha256": sha256_file(missing),
            "headers": missing_headers,
            "expected_field": "web_url",
        },
        "invalid_port": {
            "path": str(invalid_port),
            "file": INVALID_PORT_FILENAME,
            "sha256": sha256_file(invalid_port),
            "headers": headers,
            "expected_reason": "port_out_of_range",
        },
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--pg-bin", type=Path, default=Path("/opt/homebrew/opt/postgresql@17/bin"))
    p.add_argument("--evidence", type=Path)
    p.add_argument("--ui-timeout-test", action="store_true", help="Negative control: pause browser and force owned-group teardown")
    p.add_argument("--ui", action="store_true", help="Install locked frontend deps in isolated source and drive real Chrome UI")
    p.add_argument("--ledger", action="store_true", help="With the browser, drive customer-ledger invalid uploads, first selection, ledger read and persisted readback")
    p.add_argument("--doctor", action="store_true")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--expect-name", help="Deliberately wrong value proves real-path assertions fail")
    p.add_argument("--expect-ledger-ip", default="192.0.2.10", help="Deliberately wrong value proves the ledger readback assertion fails")
    a = p.parse_args()
    if a.ledger and a.ui_timeout_test:
        p.error("--ledger cannot combine with --ui-timeout-test")
    if a.ledger:
        a.ui = True
    if a.self_test:
        bad = classify(lambda: require(False, "known bad result"))[0]
        missing = classify(lambda: doctor(Path("/nonexistent-verification-runtime"), a.pg_bin))[0]
        result = {"bad_result": bad, "missing_runtime": missing,
                  "status": "PASS" if (bad, missing) == ("FAIL", "BLOCKED") else "FAIL"}
        print(json.dumps(result))
        return 0 if result["status"] == "PASS" else 1
    if a.doctor:
        status, why = classify(lambda: doctor(a.repo, a.pg_bin))
        print(json.dumps({"status": status, "reason": why}))
        return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[status]
    if not a.evidence:
        p.error("--evidence is required; use a new directory per run")
    a.repo = a.repo.resolve()
    root = a.evidence.resolve()
    root.mkdir(parents=True, exist_ok=False)
    runtime = root / "runtime"
    runtime.mkdir(mode=0o700)
    source = runtime / "source"
    source.mkdir()
    log = (root / "runtime.log").open("w")
    result = {
        "status": "NOT_RUN",
        "coverage": "synthetic local API project create/read/replay"
        + (
            " plus real-browser customer-ledger invalid uploads, preview, first selection and readback"
            if a.ledger
            else ""
        ),
        "ui": "NOT_RUN",
        "ledger": "NOT_RUN",
        "external_sources_models": "NOT_RUN",
        "cleanup": "NOT_RUN",
        "actions": [],
    }
    process = None
    pg_started = False
    ui_process = None
    env = {"PATH": os.defpath, "HOME": str(runtime), "LC_ALL": "C", "LANG": "C", "PYTHONDONTWRITEBYTECODE": "1"}

    def run(cmd, **kw):
        return subprocess.run(
            [str(x) for x in cmd], env=env, stdout=log, stderr=log, check=True, timeout=120, **kw
        )

    def psql_scalar(sql):
        return subprocess.check_output(
            [str(a.pg_bin / "psql"), "-h", "127.0.0.1", "-p", str(result["ports"]["postgres"]),
             "-U", "pilot", "-d", "pilot", "-tAc", sql],
            env=env,
            text=True,
        ).strip()

    def journey():
        nonlocal process, pg_started, env, ui_process
        result["target"] = "committed HEAD; validation assets excluded from dirty-source gate"
        py = doctor(a.repo, a.pg_bin)
        result["source_start"] = source_state(a.repo)
        result["head"] = subprocess.check_output(["git", "-C", str(a.repo), "rev-parse", "HEAD"], text=True).strip()
        result["postgres"] = subprocess.check_output([str(a.pg_bin / "postgres"), "--version"], text=True).strip()
        result["environment_limit"] = "Native PostgreSQL17 pilot, not PostgreSQL18/Docker/production equivalence"
        with (runtime / "source.tar").open("wb") as f:
            subprocess.run(["git", "-C", str(a.repo), "archive", "HEAD"], stdout=f, check=True)
        with tarfile.open(runtime / "source.tar") as archive:
            # Only versioned source, exclude any config credentials regardless of tracking.
            for member in archive.getmembers():
                if Path(member.name).name.startswith(".env"):
                    continue
                archive.extract(member, source, filter="data")
        (runtime / "source.tar").unlink()
        (runtime / "artifacts").mkdir()
        pgport, apiport = port(), port()
        while apiport == pgport:
            apiport = port()
        result["ports"] = {"postgres": pgport, "api": apiport}
        username, password = "pilot@example.org", secrets.token_urlsafe(24)
        env.update(
            PROJECT_NAME="Exposure isolated verification",
            ENVIRONMENT="local",
            SECRET_KEY=secrets.token_urlsafe(32),
            FIRST_SUPERUSER=username,
            FIRST_SUPERUSER_PASSWORD=password,
            POSTGRES_SERVER="127.0.0.1",
            POSTGRES_PORT=str(pgport),
            POSTGRES_USER="pilot",
            POSTGRES_DB="pilot",
            POSTGRES_PASSWORD="",
            NETFLOW_MAX_BYTES="52428800",
            ARTIFACT_ROOT=str(runtime / "artifacts"),
            OCTOBUS_URL="http://127.0.0.1:9",
            AGENT_COMPOSE_URL="http://127.0.0.1:9",
            MODEL_API_ENDPOINT="http://127.0.0.1:9",
            MODEL_API_KEY="",
            CLOUDATLAS_CAPSET_TOKEN="",
        )
        run([a.pg_bin / "initdb", "-D", runtime / "pgdata", "-U", "pilot", "-A", "trust", "--no-locale", "--encoding=UTF8"])
        # The private directory is mode 0700; only our disposable cluster uses trust.
        run([a.pg_bin / "pg_ctl", "-D", runtime / "pgdata", "-l", runtime / "postgres.log",
             "-o", f"-h 127.0.0.1 -p {pgport} -k ''", "-w", "start"])
        pg_started = True
        run([a.pg_bin / "createdb", "-h", "127.0.0.1", "-p", str(pgport), "-U", "pilot", "pilot"])
        backend = source / "backend"
        run([py, "-m", "alembic", "upgrade", "head"], cwd=backend)
        run([py, "-m", "app.initial_data"], cwd=backend)
        process = subprocess.Popen(
            [str(py), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(apiport)],
            cwd=backend,
            env=env,
            stdout=log,
            stderr=log,
        )
        result["api_pid"] = process.pid
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        token = None

        def request(method, path, body=None, form=None, key=None):
            headers = {}
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            if form is not None:
                data = urllib.parse.urlencode(form).encode()
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            if token:
                headers["Authorization"] = "Bearer " + token
            if key:
                headers["Idempotency-Key"] = key
            req = urllib.request.Request(
                f"http://127.0.0.1:{apiport}" + path, data=data, headers=headers, method=method
            )
            try:
                with opener.open(req, timeout=10) as resp:
                    status, payload = resp.status, json.load(resp)
            except urllib.error.HTTPError as exc:
                status, payload = exc.code, json.load(exc)
            result["actions"].append(
                {
                    "method": method,
                    "path": path,
                    "status": status,
                    "response": "[login response omitted]" if form else payload,
                }
            )
            return status, payload

        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError("API process exited before readiness")
            try:
                status, _ = request("GET", "/api/v1/projects/")
                if status == 401:
                    break
            except (OSError, TimeoutError):
                pass
            time.sleep(0.5)
        else:
            raise Blocked("API did not become ready")
        status, auth = request(
            "POST", "/api/v1/login/access-token", form={"username": username, "password": password}
        )
        require(status == 200 and auth.get("access_token"), "authentication failed")
        token = auth["access_token"]
        status, project = request("POST", "/api/v1/projects/", {"name": "verification-pilot"}, key="pilot-create")
        require(status == 201 and project.get("id"), "project creation failed")
        pid = project["id"]
        status, replay = request("POST", "/api/v1/projects/", {"name": "verification-pilot"}, key="pilot-create")
        require(status == 201 and replay.get("id") == pid, "idempotent creation duplicated project")
        status, readback = request("GET", "/api/v1/projects/" + pid)
        require(
            status == 200 and readback["name"] == (a.expect_name or "verification-pilot"),
            "persisted name mismatch",
        )
        status, listing = request("GET", "/api/v1/projects/")
        require(status == 200 and listing["count"] == 1 and listing["data"][0]["id"] == pid, "project list mismatch")
        status, profile = request("GET", f"/api/v1/projects/{pid}/customer-upload-profile")
        require(status == 200 and profile["version"] == 1, "default upload profile missing")
        result["upload_profile"] = {
            "version": profile["version"],
            "required_headers": profile["required_headers"],
        }
        query = "SELECT count(*) FROM projects;"
        saved = psql_scalar(query)
        result["db_project_count"] = saved
        require(saved == "1", "DB side effect differs from API")
        result["artifact_files"] = [
            str(f.relative_to(runtime / "artifacts")) for f in (runtime / "artifacts").rglob("*") if f.is_file()
        ]
        require(not result["artifact_files"], "unexpected artifact side effect")
        fixtures = None
        if a.ledger:
            fixtures = ledger_fixtures(root, profile["required_headers"])
            result["ledger_fixtures"] = {
                key: {name: value for name, value in item.items() if name != "path"}
                for key, item in fixtures.items()
            }
        if a.ui or a.ui_timeout_test:
            result["ui"] = "FAIL"
            bun = Path("/opt/homebrew/bin/bun")
            node = Path("/opt/homebrew/bin/node")
            if not bun.exists() or not node.exists():
                result["ui"] = "BLOCKED"
                raise Blocked("UI requires installed bun and node")
            env["PATH"] = "/opt/homebrew/bin:" + os.defpath
            env["PILOT_API"] = f"http://127.0.0.1:{apiport}"
            env["BUN_INSTALL_CACHE_DIR"] = str(runtime / "bun-cache")
            env["PILOT_LEDGER"] = "1" if a.ledger else "0"
            if fixtures is not None:
                env["PILOT_VALID_XLSX"] = fixtures["valid"]["path"]
                env["PILOT_INVALID_HEADER_XLSX"] = fixtures["invalid_header"]["path"]
                env["PILOT_INVALID_PORT_XLSX"] = fixtures["invalid_port"]["path"]
                env["PILOT_VALID_FILENAME"] = fixtures["valid"]["file"]
                env["PILOT_REQUIRED_HEADERS"] = json.dumps(profile["required_headers"])
            chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            if not chrome.exists():
                result["ui"] = "BLOCKED"
                raise Blocked("Installed Chrome unavailable")
            try:
                run([bun, "install", "--frozen-lockfile"], cwd=source)
                run(
                    [node, "-e", "const {createRequire}=require('module');"
                     "const r=createRequire(process.cwd()+'/frontend/package.json');"
                     "r('@playwright/test');r.resolve('vite/package.json')"],
                    cwd=source,
                )
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                result["ui"] = "BLOCKED"
                raise Blocked("Locked frontend dependencies unavailable; see runtime.log") from exc
            if a.ui_timeout_test:
                env["PILOT_TIMEOUT_TEST"] = "1"
            helper = Path(__file__).resolve().with_name("verify-exposure2026-ui.cjs")
            ui_process = subprocess.Popen(
                [str(node), str(helper), str(source), str(root)],
                cwd=source,
                env=env,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            result["ui_process_group"] = ui_process.pid
            (root / "ui-supervisor-owner.json").write_text(
                json.dumps({"pgid": ui_process.pid, "source": str(source)})
            )
            timeout = 20 if a.ui_timeout_test else (300 if a.ledger else 180)
            require(ui_process.wait(timeout=timeout) == 0, "Browser journey failed; see ui-result.json")
            ui_result = json.loads((root / "ui-result.json").read_text())
            result["ui"] = ui_result["status"]
            ledger_result = ui_result.get("ledger") if a.ledger else None
            if isinstance(ledger_result, dict) and ledger_result.get("status"):
                result["ledger"] = ledger_result["status"]
            require(result["ui"] == "PASS", "UI failed")
            count = psql_scalar("SELECT count(*) FROM projects;")
            result["db_project_count_after_ui"] = count
            require(count == "2", "UI did not persist exactly one additional project")
            if a.ledger:
                require(result["ledger"] == "PASS", "Ledger UI journey failed")
                ui_project = ui_result["project_id"]
                upload = ledger_result["upload"]
                upload_id = upload["upload_id"]
                raw_sha256 = upload["raw_sha256"]
                status, uploads = request("GET", f"/api/v1/projects/{ui_project}/customer-uploads")
                require(status == 200, "customer uploads readback failed")
                require(uploads.get("count") == 1, "accepted upload count mismatch")
                require(uploads.get("current_customer_upload_id") == upload_id, "current upload pointer mismatch")
                require((uploads.get("data") or [{}])[0].get("id") == upload_id, "accepted upload id mismatch")
                require((uploads.get("data") or [{}])[0].get("raw_sha256") == raw_sha256, "upload hash mismatch")
                status, ledger = request("GET", f"/api/v1/projects/{ui_project}/customer-ledger")
                require(status == 200, "customer ledger readback failed")
                require(ledger.get("upload_id") == upload_id, "ledger upload scope mismatch")
                require(ledger.get("current_upload_id") == upload_id, "ledger current upload mismatch")
                require(ledger.get("current_revision_id") is None, "first selection created a revision")
                require(ledger.get("revision") is None, "first selection returned a revision")
                require(ledger.get("count") == 2, "ledger count mismatch")
                require(ledger.get("total_records") == 2, "ledger total_records mismatch")
                require(ledger.get("unique_ips") == 2, "ledger unique_ips mismatch")
                require(ledger.get("filename") == VALID_FILENAME, "ledger filename mismatch")
                require(ledger.get("upload_sha256") == raw_sha256, "ledger upload sha mismatch")
                rows = ledger.get("data") or []
                require(len(rows) == 2, "ledger page rows mismatch")
                require(rows[0].get("canonical_ip") == a.expect_ledger_ip,
                        f"ledger first IP {rows[0].get('canonical_ip')} != expected {a.expect_ledger_ip}")
                by_ip = {row.get("canonical_ip"): row for row in rows}
                require(set(by_ip) == {"192.0.2.10", "192.0.2.11"}, "ledger IP set mismatch")
                for ip in ("192.0.2.10", "192.0.2.11"):
                    fields = by_ip[ip].get("fields") or {}
                    require(fields.get("start_port") == 443, f"ledger start_port mismatch for {ip}")
                    require(fields.get("end_port") == 443, f"ledger end_port mismatch for {ip}")
                    require(fields.get("is_web") == "否", f"ledger is_web mismatch for {ip}")
                    require(fields.get("web_url") is None, f"ledger web_url mismatch for {ip}")
                result["ledger_api_readback"] = {
                    "upload_id": ledger.get("upload_id"),
                    "current_upload_id": ledger.get("current_upload_id"),
                    "current_revision_id": ledger.get("current_revision_id"),
                    "count": ledger.get("count"),
                    "total_records": ledger.get("total_records"),
                    "unique_ips": ledger.get("unique_ips"),
                    "filename": ledger.get("filename"),
                    "upload_sha256": ledger.get("upload_sha256"),
                    "rows": [
                        {
                            "position": row.get("position"),
                            "canonical_ip": row.get("canonical_ip"),
                            "fields": row.get("fields"),
                        }
                        for row in rows
                    ],
                }
                artifact_files = [
                    f for f in (runtime / "artifacts").rglob("*") if f.is_file()
                ]
                require(len(artifact_files) == 1, "ledger run must persist exactly one artifact")
                artifact = artifact_files[0]
                artifact_hash = sha256_file(artifact)
                artifact_size = artifact.stat().st_size
                require(artifact_hash == raw_sha256, "persisted artifact hash mismatch")
                sql_current = psql_scalar(
                    f"SELECT current_customer_upload_id::text FROM projects WHERE id = '{ui_project}';"
                )
                sql_uploads = psql_scalar(
                    f"SELECT count(*) FROM customer_uploads WHERE project_id = '{ui_project}';"
                )
                sql_artifacts = psql_scalar(
                    "SELECT count(*) FROM artifacts a JOIN customer_uploads u "
                    f"ON u.artifact_id = a.id WHERE u.project_id = '{ui_project}';"
                )
                sql_artifact = psql_scalar(
                    "SELECT a.storage_key || '|' || a.sha256 || '|' || a.byte_size "
                    "FROM artifacts a JOIN customer_uploads u ON u.artifact_id = a.id "
                    f"WHERE u.project_id = '{ui_project}';"
                )
                sql_replacements = psql_scalar(
                    "SELECT count(*) FROM customer_upload_replacements "
                    f"WHERE project_id = '{ui_project}' AND candidate_upload_id = '{upload_id}';"
                )
                sql_revisions = psql_scalar(
                    f"SELECT count(*) FROM customer_ledger_revisions WHERE project_id = '{ui_project}';"
                )
                require(sql_current == upload_id, "DB current upload pointer mismatch")
                require(sql_uploads == "1", "DB accepted upload count mismatch")
                require(sql_artifacts == "1", "DB artifact count mismatch")
                require(sql_replacements == "1", "DB replacement receipt count mismatch")
                require(sql_revisions == "0", "DB revision count mismatch for first selection")
                storage_key, db_hash, db_size = sql_artifact.split("|")
                require(db_hash == raw_sha256, "DB artifact sha mismatch")
                require(int(db_size) == artifact_size, "DB artifact size mismatch")
                require(str(artifact.relative_to(runtime / "artifacts")) == storage_key, "artifact storage key mismatch")
                artifact_copy = root / "artifact-uploaded.xlsx"
                shutil.copyfile(artifact, artifact_copy)
                require(sha256_file(artifact_copy) == raw_sha256, "artifact copy hash mismatch")
                from openpyxl import load_workbook

                workbook = load_workbook(artifact_copy, read_only=True, data_only=False)
                try:
                    worksheet = workbook.worksheets[0]
                    artifact_rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
                finally:
                    workbook.close()
                require(artifact_rows[0] == list(profile["required_headers"]), "artifact headers mismatch")
                require(len(artifact_rows) == 3, "artifact row count mismatch")
                parsed = [dict(zip(artifact_rows[0], row, strict=True)) for row in artifact_rows[1:]]
                require([item["资产IP"] for item in parsed] == ["192.0.2.10", "192.0.2.11"], "artifact IPs mismatch")
                for item in parsed:
                    require(item["起始端口"] == 443 and item["结束端口"] == 443, "artifact port mismatch")
                    require(item["是否web界面"] == "否", "artifact web flag mismatch")
                    require(item["web界面url"] is None, "artifact web url mismatch")
                result["ledger_artifact"] = {
                    "files": [str(f.relative_to(runtime / "artifacts")) for f in artifact_files],
                    "storage_key": storage_key,
                    "sha256": artifact_hash,
                    "byte_size": artifact_size,
                    "copy": str(artifact_copy),
                    "copy_sha256": sha256_file(artifact_copy),
                    "headers": artifact_rows[0],
                    "rows": artifact_rows[1:],
                }
                result["ledger_sql"] = {
                    "current_customer_upload_id": sql_current,
                    "customer_uploads": sql_uploads,
                    "artifacts": sql_artifacts,
                    "artifact_row": sql_artifact,
                    "customer_upload_replacements": sql_replacements,
                    "customer_ledger_revisions": sql_revisions,
                }

    try:
        result["status"], result["reason"] = classify(journey)
    finally:
        errors = []
        if ui_process is not None:
            # Chrome's Playwright launcher owns a separate process group; capture and stop both.
            owner = root / "ui-browser-owner.json"
            if owner.exists():
                try:
                    data = json.loads(owner.read_text())
                    if data.get("source") != str(source) or not isinstance(data.get("pid"), int):
                        errors.append("Unverified browser ownership; retain runtime")
                    elif not stop_group(data["pid"]):
                        errors.append("Browser group stop unconfirmed (including EPERM)")
                except Exception as exc:
                    errors.append("Browser cleanup: " + str(exc))
            try:
                if not stop_group(ui_process.pid, ui_process):
                    errors.append("UI group stop unconfirmed (including EPERM)")
            except Exception as exc:
                errors.append("UI group cleanup: " + str(exc))
            try:
                ui_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                errors.append("UI supervisor did not stop")
            result["ui_groups_cleanup"] = "FAIL" if errors else "PASS"
        if process is not None:
            try:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            except ProcessLookupError:
                pass
            except Exception as exc:
                errors.append("API cleanup: " + str(exc))
        pgdata = runtime / "pgdata"
        # A failed/timed-out start may already own a live postmaster. Never discard its data.
        if pg_started or (pgdata / "postmaster.pid").exists():
            try:
                run([a.pg_bin / "pg_ctl", "-D", runtime / "pgdata", "-m", "fast", "-w", "stop"])
            except Exception as exc:
                errors.append(str(exc))
            if (pgdata / "postmaster.pid").exists():
                errors.append("Private postmaster.pid still exists; retaining runtime")
        if "source_start" in result:
            try:
                result["source_end"] = source_state(a.repo)
                end_head = subprocess.check_output(
                    ["git", "-C", str(a.repo), "rev-parse", "HEAD"], text=True
                ).strip()
                require(end_head == result.get("head"), "HEAD changed during verification")
            except Exception as exc:
                result["status"], result["reason"] = "FAIL", "Source changed during verification: " + str(exc)
        log.close()
        if (runtime / "postgres.log").exists():
            shutil.copyfile(runtime / "postgres.log", root / "postgres.log")
        if not errors:
            shutil.rmtree(runtime)
        result["cleanup"] = "FAIL" if errors else "PASS"
        result["cleanup_errors"] = errors
        if errors:
            result["status"] = "FAIL"
        (root / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "reason": result.get("reason"),
                    "evidence": str(root),
                    "cleanup": result["cleanup"],
                }
            )
        )
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
