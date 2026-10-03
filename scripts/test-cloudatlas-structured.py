#!/usr/bin/env python3
"""#281: real worker/OctoBus/TLS/PG/API acceptance, without customer or model access.

Run only a clean candidate. --keep preserves this invocation's isolated stack for
browser acceptance; it never reuses production DBs, tokens or source instances.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "isolated_runtime", REPO / "scripts/test-netflow-usability.py"
)
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)


class Run(_base.Run):
    def __init__(self, repo, evidence, keep, skip_build=False):
        super().__init__(repo, evidence, keep)
        self.defs = json.loads(
            (self.repo / "octobus/cloudatlas-structured/contract.json").read_text()
        )["domains"]
        self.skip_build = skip_build
        self.v.update(
            {
                f"CLOUDATLAS_{d.upper()}_CAPSET_TOKEN": secrets.token_urlsafe(24)
                for d in self.defs
            }
        )
        self.v["RUNNER_IMAGE"] = f"exposure-structured-runner:{self.sha}"
        self.v["OCTOBUS_IMAGE"] = f"exposure-structured-octobus:{self.sha}"
        self.environment = _base.env(self.v)
        self.receipts = []
        self.sources = {}
        self.token = None

    def agents(self):
        v = self.v
        values = {
            key: value
            for key, value in v.items()
            if key
            in (
                "SECRET_KEY",
                "FIRST_SUPERUSER",
                "FIRST_SUPERUSER_PASSWORD",
                "POSTGRES_DB",
                "POSTGRES_USER",
                "POSTGRES_PASSWORD",
                "AGENT_COMPOSE_AUTH_TOKEN",
            )
            or key.endswith("_CAPSET_TOKEN")
        }
        values.update(
            PROJECT_NAME="Structured CloudAtlas synthetic acceptance",
            ENVIRONMENT="local",
            POSTGRES_SERVER="host.docker.internal",
            POSTGRES_PORT=v["DB_PORT"],
            AGENT_COMPOSE_URL=f"http://host.docker.internal:{v['CONTROLLER_PORT']}",
            OCTOBUS_URL=f"http://host.docker.internal:{v['OCTOBUS_PORT']}",
            AGENT_COMPOSE_PROJECT_NAME="nf-usability",
            RUNNER_BUILD_VERSION=self.sha,
            NETFLOW_MAX_BYTES=self.v["NETFLOW_MAX_BYTES"],
        )
        protected = {
            key: {"value": value, "secret": True}
            if "TOKEN" in key or "PASSWORD" in key or key == "SECRET_KEY"
            else value
            for key, value in values.items()
        }
        (self.evidence / "agents.yml").write_text(
            json.dumps(
                {
                    "name": "nf-usability",
                    "agents": {
                        "cloudatlas-sync": {
                            "provider": "codex",
                            "image": v["RUNNER_IMAGE"],
                            "driver": {"docker": {}},
                            "env": protected,
                        }
                    },
                }
            )
        )

    def prep(self):
        super().prep()
        (self.evidence / "upstream.py").write_text(
            (
                self.repo / "scripts/fixtures/cloudatlas_structured_upstream.py"
            ).read_text()
        )
        (self.evidence / "fixture-state").mkdir()
        self.mode("complete")
        lines = [
            "#!/bin/sh",
            "set -eu",
            "octobus --addr http://octobus:9000 service import cloudatlas-structured /opt/exposure-agent/service-packages/cloudatlas-structured >/dev/null",
        ]
        for domain, definition in self.defs.items():
            identity = "s281-" + domain.replace("_", "-")
            lines += [
                f"""printf '{{"token":"%s"}}' "$FIXTURE_CLOUDATLAS_TOKEN" | octobus --addr http://octobus:9000 instance create {identity} --service cloudatlas-structured --config-json '{{"baseUrl":"https://upstream:8443/openapi/","spaceId":"281"}}' --secret - >/dev/null""",
                f"octobus --addr http://octobus:9000 capset create {identity} --name SyntheticStructured >/dev/null",
                f"octobus --addr http://octobus:9000 capset add-instance {identity} {identity} --no-all-methods >/dev/null",
                f"""octobus --addr http://octobus:9000 capset select-method {identity} {identity} '/{definition["method"]}' >/dev/null""",
                f"""printf '%s' "$CLOUDATLAS_{domain.upper()}_CAPSET_TOKEN" | octobus --addr http://octobus:9000 capset add-token {identity} fixture --name synthetic --token-stdin >/dev/null""",
            ]
        (self.evidence / "init-octobus.sh").write_text("\n".join(lines) + "\n")

    def docker(self, *args):
        args = list(args)
        if args[0] == "build":
            if self.skip_build:
                image = args[args.index("-t") + 1]
                found = json.loads(
                    subprocess.check_output(["docker", "image", "inspect", image])
                )[0]
                if (
                    found["Config"]
                    .get("Labels", {})
                    .get("org.opencontainers.image.revision")
                    != self.sha
                ):
                    raise RuntimeError(
                        "Cannot reuse an image without the exact revision label"
                    )
                return
            args[1:1] = ["--label", f"org.opencontainers.image.revision={self.sha}"]
        if args[0] == "run" and f"{self.network}-upstream" in args:
            at = args.index(self.v["RUNNER_IMAGE"])
            args[at:at] = [
                "-v",
                f"{self.evidence / 'fixture-state'}:/fixture-state",
                "-v",
                f"{self.repo / 'octobus/cloudatlas-structured/contract.json'}:/contract.json:ro",
            ]
        if args[0] == "run" and "/init.sh" in args:
            at = args.index(self.v["OCTOBUS_IMAGE"])
            extra = [
                part
                for key, value in self.v.items()
                if key.endswith("_CAPSET_TOKEN")
                for part in ("-e", f"{key}={value}")
            ]
            args[at:at] = extra
        super().docker(*args)

    def mode(self, mode):
        path = self.evidence / "fixture-state/control.json"
        staged = path.with_suffix(".tmp")
        staged.write_text(json.dumps({"mode": mode}))
        staged.replace(path)

    def api(self, path, method="GET", body=None, headers=None, expected=200):
        headers = dict(headers or {})
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.v['API_PORT']}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers=headers,
        )
        try:
            response = urllib.request.urlopen(request, timeout=120)
        except urllib.error.HTTPError as error:
            response = error
        payload = json.load(response)
        if response.status != expected:
            # Fixture values are synthetic, but auth responses are never included.
            detail = payload.get("detail", {})
            code = detail.get("code") if isinstance(detail, dict) else None
            raise RuntimeError(
                f"API {method} {path}: expected {expected}, got {response.status}, code={code}"
            )
        return payload

    def records(self, source, domain, version, **query):
        return self.api(
            f"{self.base}/sources/{source}/records?"
            + urllib.parse.urlencode({"domain": domain, "version_id": version, **query})
        )

    def browser(self):
        """Base execute calls this after real API/UI startup; drive the actual worker."""
        login = urllib.request.Request(
            f"http://127.0.0.1:{self.v['API_PORT']}/api/v1/login/access-token",
            data=urllib.parse.urlencode(
                {
                    "username": self.v["FIRST_SUPERUSER"],
                    "password": self.v["FIRST_SUPERUSER_PASSWORD"],
                }
            ).encode(),
        )
        self.token = json.load(urllib.request.urlopen(login))["access_token"]
        project = self.api(
            "/api/v1/projects/",
            "POST",
            {"name": "Structured acceptance " + self.ident},
            expected=201,
        )
        self.base = f"/api/v1/projects/{project['id']}/external-assets"
        cases = (
            "complete",
            "unknown_recovery",
            "partial",
            "empty",
            "duplicate",
            "total_drift",
            "page2_failure",
            "byte_limit",
            "type_conflict",
        )
        for domain, definition in self.defs.items():
            identity = "s281-" + domain.replace("_", "-")
            source = self.api(
                self.base + "/sources",
                "POST",
                {
                    "capability_profile": definition["profile"],
                    "instance_id": identity,
                    "capset_id": identity,
                    "space_id": "281",
                },
                expected=201,
            )["id"]
            path = f"{self.base}/sources/{source}"
            checked = self.api(path + "/validate", "POST")
            assert checked["validation_status"] == "validated", checked[
                "validation_error_code"
            ]
            self.api(path, "PATCH", {"enabled": True})
            complete_version = None
            for mode in cases:
                self.mode(mode)
                before = self.request_count()
                budget = {
                    "page_size": 1,
                    "max_pages": 1 if mode == "partial" else 3,
                    "max_records": 3,
                    "max_response_bytes": 131072,
                    "timeout_seconds": 30,
                    "retain_until": (
                        datetime.now(timezone.utc) + timedelta(hours=2)
                    ).isoformat(),
                }
                key = secrets.token_hex(16)
                task = self.api(
                    path + "/syncs",
                    "POST",
                    budget,
                    {"Idempotency-Key": key},
                    202,
                )
                if mode == "unknown_recovery":
                    original_id = task["id"]
                    task = self.api(
                        path + "/syncs/" + original_id + "/reconcile", "POST"
                    )
                    assert task["status"] == "UNKNOWN", (
                        domain,
                        "unknown was not observed",
                    )
                    recovered = self.api(
                        path + "/syncs", "POST", budget, {"Idempotency-Key": key}, 202
                    )
                    assert (
                        recovered["id"] == original_id
                        and recovered["agent_run_id"] == task["agent_run_id"]
                    )
                deadline = time.monotonic() + 120
                while (
                    task["status"] in ("PENDING", "RUNNING", "UNKNOWN")
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.5)
                    task = self.api(path + "/syncs/" + task["id"])
                    if task["status"] == "UNKNOWN":
                        # Inspect only the original session; this never retries an upstream page.
                        task = self.api(
                            path + "/syncs/" + task["id"] + "/reconcile", "POST"
                        )
                if task["status"] in ("PENDING", "RUNNING", "UNKNOWN"):
                    raise RuntimeError(
                        f"{domain}/{mode}: unresolved original task {task['id']}; no retry"
                    )
                entry = next(
                    item for item in task["domains"] if item["domain"] == domain
                )
                expected = (
                    "PARTIAL_SUCCEEDED"
                    if mode == "partial"
                    else "SUCCEEDED"
                    if mode in ("complete", "empty", "unknown_recovery")
                    else "FAILED"
                )
                assert task["status"] == expected, (
                    domain,
                    mode,
                    task["status"],
                    task["error_code"],
                    entry["error_code"],
                )
                count = self.request_count() - before
                expected_calls = (
                    1
                    if mode in ("partial", "empty", "byte_limit", "type_conflict")
                    else 2
                )
                assert count == expected_calls, (domain, mode, count)
                if mode in ("complete", "partial", "empty"):
                    version = entry["version_id"]
                    rows = self.records(source, domain, version)
                    n = 0 if mode == "empty" else 1 if mode == "partial" else 2
                    assert rows["count"] == n and rows["version"]["complete"] == (
                        mode != "partial"
                    )
                    assert rows["version"]["omitted_field_count"] == n
                    assert rows["version"]["filter"] == definition["filters"]
                    if mode == "complete":
                        complete_version = version
                        first = self.records(source, domain, version, limit=1, skip=0)
                        second = self.records(source, domain, version, limit=1, skip=1)
                        assert first["count"] == second["count"] == 2
                        assert len(first["data"]) == len(second["data"]) == 1
                        assert first["data"][0]["id"] != second["data"][0]["id"]
                        ids = {row["source_id"] for row in rows["data"]}
                        assert ids == {"900719925474099312345", "900719925474099312346"}
                        for row in rows["data"]:
                            assert (
                                not {"unknown_private_fixture_field", "headers", "data"}
                                & row["fields"].keys()
                            )
                            detail = self.api(
                                path + "/versions/" + version + "/records/" + row["id"]
                            )
                            assert detail["record"]["fields"] == row["fields"]
                        if definition["text_fields"]:
                            assert (
                                self.records(source, domain, version, q="%_\\")["count"]
                                == 2
                            )
                            assert (
                                self.records(
                                    source, domain, version, q="definitely-absent"
                                )["count"]
                                == 0
                            )
                        elif domain == "openport":
                            assert (
                                self.records(
                                    source, domain, version, ip="2001:0db8::7"
                                )["count"]
                                == 2
                            )
                        self.sources[domain] = {
                            "source_id": source,
                            "version_id": version,
                            "record_id": rows["data"][0]["id"],
                            "profile": definition["profile"],
                        }
                assert (
                    complete_version
                    and self.records(source, domain, complete_version)["count"] == 2
                )
                self.receipts.append(
                    {
                        "domain": domain,
                        "scenario": mode,
                        "status": "PASS",
                        "task_id": task["id"],
                        "upstream_calls": count,
                    }
                )
                (self.evidence / "scenario-results.json").write_text(
                    json.dumps(self.receipts, indent=2)
                )
                print(f"{domain}: {mode} PASS", flush=True)
        # Fixed versions remain locally readable after access revocation and restore.
        for domain, info in self.sources.items():
            path = f"{self.base}/sources/{info['source_id']}"
            self.api(path, "PATCH", {"data_access_enabled": False})
            self.api(
                path
                + "/records?"
                + urllib.parse.urlencode(
                    {"domain": domain, "version_id": info["version_id"]}
                ),
                expected=403,
            )
            self.api(path, "PATCH", {"data_access_enabled": True})
        self.docker("stop", f"{self.network}-upstream")
        before = self.request_count()
        for domain, info in self.sources.items():
            assert (
                self.records(info["source_id"], domain, info["version_id"])["count"]
                == 2
            )
        assert self.request_count() == before
        receipt = {
            "sha": self.sha,
            "project_id": project["id"],
            "sources": self.sources,
            "api_url": f"http://127.0.0.1:{self.v['API_PORT']}",
            "ui_url": f"http://127.0.0.1:{self.v['UI_PORT']}",
            "network": self.network,
            "containers": self.names,
            "pids": [process.pid for process in self.procs],
            "offline_api": "PASS",
            "browser": "NOT_RUN",
        }
        (self.evidence / "runtime.json").write_text(json.dumps(receipt, indent=2))
        private = self.evidence / "browser-token"
        private.write_text(self.token)
        private.chmod(0o600)

    def request_count(self):
        path = self.evidence / "fixture-state/requests.jsonl"
        return len(path.read_text().splitlines()) if path.exists() else 0

    def finish(self):
        if self.keep:
            return
        super().finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    if args.evidence.exists() and (
        args.evidence.is_symlink() or any(args.evidence.iterdir())
    ):
        raise SystemExit("Evidence must be a new or empty private directory")
    if subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=args.repo, text=True
    ).strip():
        raise SystemExit(
            "Commit the candidate first; this acceptance requires a clean checkout"
        )
    result = Run(args.repo, args.evidence, args.keep, args.skip_build).execute()
    if result == 0 and args.keep:
        print(
            "STACK_READY: isolated API/UI retained for browser acceptance; interrupt after verification.",
            flush=True,
        )
        while True:
            time.sleep(30)
    return result


if __name__ == "__main__":
    sys.exit(main())
