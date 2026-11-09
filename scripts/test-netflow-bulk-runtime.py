#!/usr/bin/env python3
"""Synthetic bulk acceptance through the real agent-compose guest and HTTP API.

Reuse the existing isolated usability harness. No deployed service, source,
credential, model or production database is read or changed.

Scenarios:
- capacity (default): the pre-existing 128 MB / 4-file capacity path and its
  raw_count > 100000 assertion, pre-claim cancellation, a real-UI live-lease
  cancellation, and a terminal UI view of the capacity task;
- progress (also `--scenario small`): a 4 MB / 4-file success with HTTP and
  independent PostgreSQL readback, pre-claim cancellation, a real-UI live-lease
  cancellation at 16 MB then a bounded 64 MB retry, and a real Results-page
  polling run from unfinished to terminal success;
- all: both scenarios in one isolated runtime.

A clean checkout is required because the result is tied to the recorded commit.
"""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import httpx
import yaml

module_path = Path(__file__).with_name("test-netflow-usability.py")
spec = importlib.util.spec_from_file_location("isolated_netflow_harness", module_path)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

PROGRESS_KEYS = (
    "project_id",
    "analysis_id",
    "dataset_id",
    "context_revision_id",
    "network_namespace",
    "test_fixture",
    "status",
    "phase",
    "cancel_requested",
    "heartbeat_at",
    "lease_until",
    "files_completed",
    "files_total",
    "rows_normalized",
)
UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
UI_SUCCESS_BYTES = 64_000_000
UI_SUCCESS_FILES = 4
UI_CANCEL_SIZES = ((16_000_000, "16mb"), (64_000_000, "64mb"))


def progress_sample(value):
    return {key: value.get(key) for key in PROGRESS_KEYS}


def iso_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_current_at_success(
    snapshot,
    project_id,
    analysis_id,
    fixture,
    final,
    terminal_at,
    cancel_started_at,
):
    if not isinstance(snapshot, dict):
        raise AssertionError("success terminal current snapshot is missing")
    assert snapshot.get("response_status") == 200, snapshot
    at = snapshot.get("at")
    assert isinstance(at, str) and at, snapshot
    assert isinstance(terminal_at, str) and terminal_at, snapshot
    assert isinstance(cancel_started_at, str) and cancel_started_at, snapshot
    read_at = iso_time(at)
    assert read_at >= iso_time(terminal_at), (at, terminal_at)
    assert read_at < iso_time(cancel_started_at), (at, cancel_started_at)
    body = snapshot.get("body")
    assert isinstance(body, dict), snapshot
    assert body.get("project_id") == project_id, snapshot
    current = body.get("current")
    assert isinstance(current, dict), snapshot
    assert current.get("project_id") == project_id, snapshot
    assert current.get("analysis_id") == analysis_id, snapshot
    assert current.get("dataset_id") == fixture["dataset_id"], snapshot
    assert (
        current.get("context_revision_id") == fixture["context_revision_id"]
    ), snapshot
    assert current.get("status") == final["status"], snapshot
    assert current.get("pipeline_complete") is True, snapshot
    assert current.get("can_read_result") is True, snapshot
    assert current.get("result") is not None, snapshot
    return {
        "analysis_id": current["analysis_id"],
        "status": current["status"],
        "read_at": at,
        "response_status": snapshot["response_status"],
    }


class Run(base.Run):
    def __init__(self, repo, evidence, scenario="capacity"):
        super().__init__(repo, evidence, False)
        self.scenario = scenario
        self.snapshots = self.evidence / "snapshots"
        self._cleanup = None
        self.v.update(
            NETFLOW_BULK_ROOT=str(self.snapshots),
            NETFLOW_BULK_MEMORY_MB="128",
            NETFLOW_BULK_THREADS="1",
            NETFLOW_BULK_RSS_BYTES=str(768 * 1024**2),
        )
        self.v["RUNNER_IMAGE"] = f"nf-bulk-304-runner:{self.sha}"
        self.environment = base.env(self.v)

    def check_identity(self):
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=self.repo, text=True
        )
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, text=True
        ).strip()
        if dirty or head != self.sha:
            raise RuntimeError(
                "Checkout changed or is dirty; no fixed-commit acceptance can be published"
            )

    def agents(self):
        self.snapshots.mkdir(parents=True, exist_ok=True, mode=0o700)
        super().agents()
        path = self.evidence / "agents.yml"
        value = yaml.safe_load(path.read_text())
        value["agents"].pop("cloudatlas-sync")
        agent = value["agents"]["netflow-processor"]
        agent["env"].update(
            NETFLOW_BULK_ROOT="/app/netflow-bulk-inputs",
            NETFLOW_BULK_MEMORY_MB="128",
            NETFLOW_BULK_THREADS="1",
            NETFLOW_BULK_RSS_BYTES=str(768 * 1024**2),
        )
        agent["volumes"].append(
            {
                "type": "bind",
                "source": str(self.snapshots),
                "target": "/app/netflow-bulk-inputs",
                "read_only": True,
            }
        )
        path.write_text(yaml.safe_dump(value, sort_keys=False))

    def infra(self):
        v = self.v
        self.docker(
            "build",
            "--pull=false",
            "-f",
            "backend/Dockerfile.runner",
            "--build-arg",
            f"RUNNER_BUILD_VERSION={self.sha}",
            "-t",
            v["RUNNER_IMAGE"],
            ".",
        )
        self.docker("network", "create", self.network)
        db = f"{self.network}-db"
        self.docker(
            "run",
            "-d",
            "--name",
            db,
            "--memory",
            "512m",
            "--cpus",
            "1",
            "--network",
            self.network,
            "--network-alias",
            "db",
            "-p",
            f"127.0.0.1:{v['DB_PORT']}:5432",
            "-e",
            f"POSTGRES_DB={v['POSTGRES_DB']}",
            "-e",
            f"POSTGRES_USER={v['POSTGRES_USER']}",
            "-e",
            f"POSTGRES_PASSWORD={v['POSTGRES_PASSWORD']}",
            "postgres:18",
        )
        self.names.append(db)
        controller = f"{self.network}-controller"
        self.docker(
            "run",
            "-d",
            "--name",
            controller,
            "--memory",
            "512m",
            "--cpus",
            "1",
            "--network",
            self.network,
            "--network-alias",
            "agent-compose",
            "-p",
            f"127.0.0.1:{v['CONTROLLER_PORT']}:7410",
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock",
            "-v",
            f"{self.data}:{self.data}",
            "-v",
            f"{self.artifacts}:{self.artifacts}",
            "-v",
            f"{self.snapshots}:{self.snapshots}:ro",
            "-e",
            f"DATA_ROOT={self.data}",
            "-e",
            f"AGENT_COMPOSE_AUTH_TOKEN={v['AGENT_COMPOSE_AUTH_TOKEN']}",
            base.CONTROLLER,
            "daemon",
        )
        self.names.append(controller)
        self.docker(
            "run",
            "--rm",
            "--entrypoint",
            "/bin/sh",
            "--network",
            self.network,
            "-v",
            f"{self.evidence / 'agents.yml'}:/agents.yml:ro",
            "-e",
            f"AGENT_COMPOSE_AUTH_TOKEN={v['AGENT_COMPOSE_AUTH_TOKEN']}",
            base.CONTROLLER,
            "-ec",
            'for i in 1 2 3 4 5 6 7 8 9 10; do if agent-compose --host http://agent-compose:7410 auth login --token "$AGENT_COMPOSE_AUTH_TOKEN" >/dev/null; then exec agent-compose --host http://agent-compose:7410 --file /agents.yml up --json; fi; sleep 1; done; exit 1',
        )

    # ---- shared evidence and API helpers ----------------------------------
    @staticmethod
    def append_jsonl(path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, sort_keys=True, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(json.dumps(value, indent=2, default=str) + "\n")

    def sql(self, query):
        environment = base.env(
            {**self.v, "PGPASSWORD": self.v["POSTGRES_PASSWORD"]}
        )
        completed = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "-e",
                "PGPASSWORD",
                f"{self.network}-db",
                "psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                self.v["POSTGRES_USER"],
                "-d",
                self.v["POSTGRES_DB"],
                "-t",
                "-A",
                "-F",
                "|",
                "-c",
                query,
            ],
            env=environment,
            text=True,
            capture_output=True,
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip().splitlines()
            raise RuntimeError(
                "private PostgreSQL readback failed: "
                + (detail[-1] if detail else "no detail")
            )
        return [
            line.split("|") for line in completed.stdout.splitlines() if line.strip()
        ]

    def bulk_sql(self, analysis_id):
        if not UUID.match(analysis_id):
            raise RuntimeError("refusing SQL readback for a non-UUID analysis")
        job = self.sql(
            "SELECT j.analysis_id, a.status, j.phase, "
            "coalesce(to_char(j.lease_until AT TIME ZONE 'UTC', "
            "'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), ''), "
            "coalesce(to_char(j.heartbeat_at AT TIME ZONE 'UTC', "
            "'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), ''), "
            "j.cancel_requested, "
            "(SELECT count(*) FROM netflow_bulk_members m "
            "WHERE m.dataset_id = j.dataset_id AND m.complete), "
            "(SELECT count(*) FROM netflow_bulk_members m "
            "WHERE m.dataset_id = j.dataset_id), "
            "(SELECT coalesce(sum(m.raw_count), 0) FROM netflow_bulk_members m "
            "WHERE m.dataset_id = j.dataset_id), "
            "(SELECT coalesce(sum(m.invalid_count), 0) FROM netflow_bulk_members m "
            "WHERE m.dataset_id = j.dataset_id) "
            "FROM netflow_bulk_jobs j "
            "JOIN netflow_analyses a ON a.id = j.analysis_id "
            f"WHERE j.analysis_id = '{analysis_id}'"
        )
        if len(job) != 1:
            raise RuntimeError(f"expected one bulk job row, got {len(job)}")
        row = job[0]
        members = self.sql(
            "SELECT m.file_id, m.complete, m.raw_count, m.invalid_count, m.byte_size "
            "FROM netflow_bulk_members m JOIN netflow_bulk_jobs j "
            "ON j.dataset_id = m.dataset_id "
            f"WHERE j.analysis_id = '{analysis_id}' ORDER BY m.file_id"
        )
        return {
            "analysis_id": row[0],
            "analysis_status": row[1],
            "phase": row[2],
            "lease_until": row[3] or None,
            "heartbeat_at": row[4] or None,
            "cancel_requested": row[5] == "t",
            "files_completed": int(row[6]),
            "files_total": int(row[7]),
            "rows_normalized": int(row[8]),
            "invalid_rows": int(row[9]),
            "members": [
                {
                    "file_id": member[0],
                    "complete": member[1] == "t",
                    "raw_count": int(member[2]),
                    "invalid_count": int(member[3]),
                    "byte_size": int(member[4]),
                }
                for member in members
            ],
        }

    def dataset(
        self, client, project_id, source_id, byte_target, files, seed, start=True
    ):
        from app.netflow_bulk.__main__ import generate
        from app.netflow_bulk.storage import seal

        source = self.evidence / f"input-{source_id}"
        input_info = generate(
            source,
            byte_target=byte_target,
            files=files,
            seed=seed,
            width=1024,
            ipv6=0.35,
            duplicate=0.1,
            objects=100000,
            peers=500000,
            hotspot=0.1,
            overlap=0.1,
        )
        ready_id, _ = seal(
            source,
            self.snapshots,
            tenant="00000000-0000-0000-0000-000000000001",
            project=project_id,
            source_id=source_id,
        )
        root = f"/api/v1/projects/{project_id}"
        registration = client.post(
            root + "/netflow-bulk/datasets",
            headers={"Idempotency-Key": f"register-{source_id}"},
            json={"source_id": source_id, "ready_id": ready_id},
        )
        registration.raise_for_status()
        dataset_id = registration.json()["dataset_id"]
        context = client.post(
            root + f"/netflow-datasets/{dataset_id}/processing-contexts",
            headers={"Idempotency-Key": f"context-{source_id}"},
            json={
                "expected_parent_id": None,
                "network_namespace": "synthetic-bulk",
                "state": "CONFIRMED",
                "collection_scope": "runtime",
                "collection_scope_evidence": "Synthetic isolated runtime scope.",
                "source_position_evidence": "Synthetic exporter declares SRC position only, not ownership.",
                "nat_context": "unknown",
                "observation_point": {"id": "fixture", "view": "UNKNOWN"},
                "sampling": {"mode": "unknown", "rate": None},
            },
        )
        context.raise_for_status()
        item = {
            "root": root,
            "dataset_id": dataset_id,
            "context_revision_id": context.json()["context_revision_id"],
            "input": input_info,
        }
        if not start:
            return item
        queued = client.post(
            root + f"/netflow-datasets/{dataset_id}/analyses",
            headers={"Idempotency-Key": f"analysis-{source_id}"},
            json={"context_revision_id": item["context_revision_id"]},
        )
        queued.raise_for_status()
        item["analysis_id"] = queued.json()["analysis_id"]
        return item

    @staticmethod
    def progress(client, root, analysis_id):
        response = client.get(
            root + f"/netflow-bulk/analyses/{analysis_id}/progress"
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def check_progress_identity(value, project_id, item):
        assert value["project_id"] == project_id
        assert value["analysis_id"] == item["analysis_id"]
        assert value["dataset_id"] == item["dataset_id"]
        assert value["context_revision_id"] == item["context_revision_id"]
        assert value["network_namespace"] == "synthetic-bulk"
        assert value["provenance"]["backend"] == "netflow-bulk-v1"
        assert isinstance(value["test_fixture"], bool)

    @staticmethod
    def terminal(value):
        if value["status"] in ("SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"):
            return (
                value["phase"] == "SUCCEEDED"
                and value["files_completed"] == value["files_total"]
            )
        if value["status"] == "FAILED":
            return value["phase"] in ("FAILED", "CANCELLED")
        return False

    def wait_progress(
        self, client, project_id, item, timeout, interval, samples_path=None
    ):
        samples = []
        if samples_path is not None:
            samples_path.unlink(missing_ok=True)
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            value = self.progress(client, item["root"], item["analysis_id"])
            self.check_progress_identity(value, project_id, item)
            sample = progress_sample(value)
            samples.append(sample)
            if samples_path is not None:
                self.append_jsonl(samples_path, sample)
            if self.terminal(value):
                return value, samples
            time.sleep(interval)
        raise RuntimeError(
            f"progress did not become terminal: {item['analysis_id']}; "
            f"last={samples[-1] if samples else None}"
        )

    def current(self, client, project_id):
        response = client.get(
            f"/api/v1/projects/{project_id}/netflow-results/current"
        )
        response.raise_for_status()
        return response.json()

    # ---- scenario: small success ------------------------------------------
    def small_success(self, client, project_id):
        item = self.dataset(
            client, project_id, "progress-success", 4_000_000, 4, 404
        )
        samples_path = self.evidence / "progress-success-samples.jsonl"
        final, samples = self.wait_progress(
            client,
            project_id,
            item,
            timeout=300,
            interval=0.05,
            samples_path=samples_path,
        )
        sql = self.bulk_sql(item["analysis_id"])
        self.write_json(self.evidence / "progress-success-sql.json", sql)
        observations = client.get(
            item["root"] + f"/netflow-analyses/{item['analysis_id']}/observations",
            params={"limit": 1},
        )
        observations.raise_for_status()
        observed = observations.json()
        current = self.current(client, project_id)
        result = {
            "analysis_id": item["analysis_id"],
            "dataset_id": item["dataset_id"],
            "input": item["input"],
            "terminal": progress_sample(final),
            "samples": samples,
            "samples_path": str(samples_path.relative_to(self.evidence)),
            "sql_readback": sql,
            "observation_raw_record_count": observed["raw_record_count"],
            "observation_count": observed["total_observations"],
            "current_analysis_id": (
                current["current"]["analysis_id"] if current["current"] else None
            ),
        }
        self.write_json(self.evidence / "progress-success-partial.json", result)
        assert final["status"] in ("SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"), final
        assert final["phase"] == "SUCCEEDED", final
        assert final["files_completed"] == 4 and final["files_total"] == 4, final
        assert final["rows_normalized"] == item["input"]["rows"], (
            final["rows_normalized"],
            item["input"]["rows"],
        )
        assert final["heartbeat_at"] is not None, final
        assert any(
            sample["status"] in ("PENDING", "RUNNING", "UNKNOWN")
            for sample in samples
        ), samples[:3]
        assert any(sample["heartbeat_at"] for sample in samples), samples[:5]
        assert sql["analysis_status"] in ("SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"), sql
        assert sql["phase"] == "SUCCEEDED", sql
        assert sql["lease_until"] is None, sql
        assert sql["heartbeat_at"] is not None, sql
        assert sql["cancel_requested"] is False, sql
        assert sql["files_completed"] == 4 and sql["files_total"] == 4, sql
        assert sql["rows_normalized"] == item["input"]["rows"], sql
        assert all(member["complete"] for member in sql["members"]), sql
        assert observed["raw_record_count"] == item["input"]["rows"], observed[
            "raw_record_count"
        ]
        assert observed["total_observations"] > 0, observed
        assert current["current"] is not None, current
        assert current["current"]["analysis_id"] == item["analysis_id"], current
        assert current["current"]["can_read_result"] is True, current
        self.write_json(self.evidence / "progress-success.json", result)
        return result, item["analysis_id"]

    # ---- scenario: preserved default capacity path ------------------------
    def capacity(self, client, project_id):
        item = self.dataset(client, project_id, "runtime", 128_000_000, 4, 304)
        root = item["root"]
        samples_path = self.evidence / "progress-capacity-samples.jsonl"
        samples_path.unlink(missing_ok=True)
        started = time.monotonic()
        value = None
        progress_final = None
        progress_samples = []
        while time.monotonic() - started < 600:
            response = client.get(root + f"/netflow-analyses/{item['analysis_id']}")
            response.raise_for_status()
            value = response.json()
            progress = self.progress(client, root, item["analysis_id"])
            self.check_progress_identity(progress, project_id, item)
            sample = progress_sample(progress)
            progress_samples.append(sample)
            self.append_jsonl(samples_path, sample)
            if self.terminal(progress):
                progress_final = progress
            if value["status"] in ("SUCCEEDED", "SUCCEEDED_WITH_WARNINGS", "FAILED"):
                break
            time.sleep(1)
        assert value is not None, "capacity analysis did not return a detail"
        assert value["status"] in ("SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"), value[
            "error_code"
        ]
        assert progress_final is not None, (
            progress_samples[-1] if progress_samples else None
        )
        assert progress_final["phase"] == "SUCCEEDED", progress_final
        assert progress_final["files_completed"] == 4, progress_final
        assert progress_final["files_total"] == 4, progress_final
        assert progress_final["rows_normalized"] == item["input"]["rows"], (
            progress_final["rows_normalized"],
            item["input"]["rows"],
        )
        observations = client.get(
            root + f"/netflow-analyses/{item['analysis_id']}/observations",
            params={"limit": 25},
        )
        observations.raise_for_status()
        assert observations.json()["raw_record_count"] > 100000
        peers = client.get(
            root + f"/netflow-analyses/{item['analysis_id']}/peers",
            params={"limit": 25},
        )
        peers.raise_for_status()
        current = self.current(client, project_id)
        assert current["current"] is not None, current
        assert current["current"]["analysis_id"] == item["analysis_id"], current
        report = {
            "input": item["input"],
            "analysis_id": item["analysis_id"],
            "dataset_id": item["dataset_id"],
            "context_revision_id": item["context_revision_id"],
            "status": value["status"],
            "quality": value["quality"],
            "error_code": value["error_code"],
            "seconds": time.monotonic() - started,
            "observation_count": observations.json()["total_observations"],
            "peer_count": peers.json()["total_peers"],
            "terminal_progress": progress_sample(progress_final),
            "progress_samples_path": str(samples_path.relative_to(self.evidence)),
            "progress_samples": progress_samples,
        }
        self.write_json(self.evidence / "progress-capacity.json", report)
        return report, item["analysis_id"]

    # ---- scenario: pre-claim cancellation ---------------------------------
    def preclaim_cancel(self, client, project_id, prior_success):
        attempts = []
        for number in range(3):
            item = self.dataset(
                client,
                project_id,
                f"preclaim-{number}",
                1_000_000,
                1,
                700 + number,
            )
            current_before = self.current(client, project_id)
            if current_before["current"] is not None:
                prior_success = current_before["current"]["analysis_id"]
            before = self.progress(client, item["root"], item["analysis_id"])
            self.check_progress_identity(before, project_id, item)
            ack = client.post(
                item["root"] + f"/netflow-bulk/analyses/{item['analysis_id']}/cancel"
            )
            ack.raise_for_status()
            acknowledgement = ack.json()
            if acknowledgement["analysis_id"] != item["analysis_id"]:
                raise RuntimeError("cancel response identity mismatch")
            attempt = {
                "analysis_id": item["analysis_id"],
                "before_cancel": progress_sample(before),
                "ack": acknowledgement,
            }
            samples_path = (
                self.evidence / f"progress-preclaim-{number}-samples.jsonl"
            )
            if acknowledgement["cancel_requested"] is not True:
                # The task was already terminal when cancel arrived. This is a
                # pre-claim miss, not a reason to abort the remaining scenarios.
                final, samples = self.wait_progress(
                    client,
                    project_id,
                    item,
                    timeout=120,
                    interval=0.05,
                    samples_path=samples_path,
                )
                attempt["terminal"] = progress_sample(final)
                attempt["samples"] = samples
                attempt["samples_path"] = str(samples_path.relative_to(self.evidence))
                attempt["miss"] = True
                attempt["reason"] = "cancel_not_requested"
                attempts.append(attempt)
                if final["status"] in ("SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"):
                    prior_success = item["analysis_id"]
                continue
            final, samples = self.wait_progress(
                client,
                project_id,
                item,
                timeout=120,
                interval=0.05,
                samples_path=samples_path,
            )
            attempt["terminal"] = progress_sample(final)
            attempt["samples"] = samples
            attempt["samples_path"] = str(samples_path.relative_to(self.evidence))
            attempt["preclaim"] = (
                final["status"] == "FAILED"
                and final["phase"] == "CANCELLED"
                and final["heartbeat_at"] is None
                and final["lease_until"] is None
            )
            attempts.append(attempt)
            if final["status"] in ("SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"):
                prior_success = item["analysis_id"]
            if attempt["preclaim"]:
                current = self.current(client, project_id)
                assert current["current"] is not None, current
                assert current["current"]["analysis_id"] == prior_success, current
                assert (
                    current["latest_attempt"]["analysis_id"] == item["analysis_id"]
                ), current
                result = {
                    "status": "PASS",
                    "attempts": attempts,
                    "preclaim_attempts": number + 1,
                    "current_analysis_id": current["current"]["analysis_id"],
                }
                self.write_json(
                    self.evidence / "progress-preclaim-cancel.json", result
                )
                return result
        result = {
            "status": "MISSED",
            "attempts": attempts,
            "current_analysis_id": prior_success,
        }
        self.write_json(self.evidence / "progress-preclaim-cancel.json", result)
        return result

    # ---- UI fixtures and evidence -----------------------------------------
    @staticmethod
    def ui_fixture(item, label, input_bytes, files=4):
        return {
            "label": label,
            "dataset_id": item["dataset_id"],
            "context_revision_id": item["context_revision_id"],
            "input_bytes": input_bytes,
            "input_rows": item["input"]["rows"],
            "files": files,
        }

    def browser(self, project_id, success, cancel, terminal):
        test_env = base.env(
            {
                **self.v,
                "RUN_NETFLOW_BULK_UI_E2E": "1",
                "PLAYWRIGHT_BASE_URL": f"http://127.0.0.1:{self.ports['ui']}",
                "NETFLOW_BULK_UI_EVIDENCE": str(self.evidence),
                "NETFLOW_BULK_UI_PROJECT": project_id,
                "NETFLOW_BULK_UI_CANCEL": json.dumps(cancel),
            }
        )
        if success is not None:
            test_env["NETFLOW_BULK_UI_SUCCESS"] = json.dumps(success)
        if terminal:
            test_env["NETFLOW_BULK_UI_TERMINAL"] = json.dumps(terminal)
        self.run(
            [
                "bunx",
                "playwright",
                "test",
                "--config=playwright.netflow-bulk.config.ts",
                "--reporter=line",
            ],
            self.repo / "frontend",
            test_env,
        )
        evidence = {}
        for name in ("ui-progress.json", "ui-cancel.json", "ui-terminal.json"):
            path = self.evidence / name
            if path.exists():
                evidence[name.removesuffix(".json")] = json.loads(path.read_text())
        return evidence

    def assert_ui_success(self, client, project_id, ui, prior_success):
        value = ui.get("ui-progress")
        if not value or value.get("status") != "PASS":
            raise RuntimeError("real Results-page progress evidence is missing")
        assert value["route_interception"] is False, value
        assert value["first_event"]["response_status"] == 200, value["first_event"]
        assert value["terminal_event"]["response_status"] == 200, value[
            "terminal_event"
        ]
        assert (
            f"/projects/{project_id}/netflow-results"
            in value["first_event"]["page_url"]
        ), value["first_event"]
        assert (self.evidence / value["events_path"]).exists(), value["events_path"]
        fixture = value["fixture"]
        analysis_id = value["analysis_id"]
        assert value["start"]["analysis_id"] == analysis_id, value["start"]
        assert value["terminal_event_index"] > value["first_event_index"], value
        first = value["first_event"]["body"]
        final = value["terminal_event"]["body"]
        assert first is not None and final is not None, value
        assert value["first_event"]["terminal"] is False, value["first_event"]
        assert value["terminal_event"]["terminal"] is True, value["terminal_event"]
        assert first["project_id"] == project_id, first
        assert first["analysis_id"] == analysis_id, first
        assert first["dataset_id"] == fixture["dataset_id"], first
        assert first["context_revision_id"] == fixture["context_revision_id"], first
        assert first["provenance"]["backend"] == "netflow-bulk-v1", first
        assert final["analysis_id"] == analysis_id, final
        assert final["phase"] == "SUCCEEDED", final
        assert final["files_completed"] == final["files_total"], final
        assert final["files_completed"] == UI_SUCCESS_FILES, final
        assert final["heartbeat_at"] is not None, final
        assert final["rows_normalized"] == fixture["input_rows"], final
        assert value["current_while_running_analysis_id"] == prior_success, value
        assert "Analysis completed" not in value["visible_first"], value
        assert "Completed with coverage warnings" not in value["visible_first"], value
        assert "Analysis completed" in value["visible_terminal"], value
        assert (
            f"Files complete: {final['files_completed']} / {final['files_total']}"
            in value["visible_terminal"]
        ), value
        item = {
            "root": f"/api/v1/projects/{project_id}",
            "analysis_id": analysis_id,
            "dataset_id": fixture["dataset_id"],
            "context_revision_id": fixture["context_revision_id"],
        }
        progress = self.progress(client, item["root"], analysis_id)
        self.check_progress_identity(progress, project_id, item)
        assert progress["status"] in ("SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"), progress
        assert progress["phase"] == "SUCCEEDED", progress
        assert progress["files_completed"] == UI_SUCCESS_FILES, progress
        assert progress["files_total"] == UI_SUCCESS_FILES, progress
        assert progress["rows_normalized"] == fixture["input_rows"], progress
        sql = self.bulk_sql(analysis_id)
        self.write_json(self.evidence / "progress-ui-success-sql.json", sql)
        assert sql["analysis_status"] in ("SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"), sql
        assert sql["phase"] == "SUCCEEDED", sql
        assert sql["lease_until"] is None, sql
        assert sql["heartbeat_at"] is not None, sql
        assert sql["files_completed"] == UI_SUCCESS_FILES, sql
        assert sql["files_total"] == UI_SUCCESS_FILES, sql
        assert sql["rows_normalized"] == fixture["input_rows"], sql
        assert all(member["complete"] for member in sql["members"]), sql
        cancel_attempts = (ui.get("ui-cancel") or {}).get("attempts") or []
        assert cancel_attempts, "cancel attempts evidence is missing"
        cancel_starts = []
        for attempt in cancel_attempts:
            started_at = attempt.get("started_at")
            assert isinstance(started_at, str) and started_at, attempt
            cancel_starts.append(started_at)
        current_at_success = check_current_at_success(
            value.get("current_at_success"),
            project_id,
            analysis_id,
            fixture,
            final,
            value["terminal_event"]["at"],
            min(cancel_starts, key=iso_time),
        )
        result = {
            "analysis_id": analysis_id,
            "fixture": fixture,
            "start": value["start"],
            "events_path": value["events_path"],
            "first_nonterminal": first,
            "terminal": final,
            "current_while_running_analysis_id": value[
                "current_while_running_analysis_id"
            ],
            "current_at_success": current_at_success,
            "visible_first": value["visible_first"],
            "visible_terminal": value["visible_terminal"],
            "sql_readback": sql,
        }
        self.write_json(self.evidence / "progress-ui-success.json", result)
        return result

    def assert_ui_cancel(self, client, project_id, ui):
        value = ui.get("ui-cancel")
        if not value or value.get("status") != "PASS":
            raise RuntimeError(
                "real-UI live-lease cancellation was not observed; "
                "see ui-cancel.json and ui-cancel-attempts/"
            )
        assert value["route_interception"] is False, value
        prior_success = value.get("current_while_running_analysis_id")
        assert isinstance(prior_success, str) and UUID.match(prior_success), value
        assert (self.evidence / "ui-cancel-attempts").is_dir()
        for attempt in value["attempts"]:
            assert (self.evidence / attempt["events_path"]).exists(), attempt
            assert (
                self.evidence / "ui-cancel-attempts" / attempt["events_path"].split("/")[-2] / "attempt.json"
            ).exists(), attempt
        fixture = value["fixture"]
        analysis_id = value["analysis_id"]
        assert value["start"]["analysis_id"] == analysis_id, value["start"]
        assert value["ack"]["status"] == 200, value["ack"]
        assert value["ack"]["body"]["analysis_id"] == analysis_id, value["ack"]
        assert value["ack"]["body"]["cancel_requested"] is True, value["ack"]
        assert value["live_lease"]["response_status"] == 200, value["live_lease"]
        assert value["live_lease"]["body"]["status"] == "RUNNING", value["live_lease"]
        assert value["live_lease"]["body"]["lease_until"] is not None, value[
            "live_lease"
        ]
        assert value["live_lease"]["body"]["analysis_id"] == analysis_id, value[
            "live_lease"
        ]
        assert value["terminal"]["response_status"] == 200, value["terminal"]
        assert value["terminal"]["body"]["status"] == "FAILED", value["terminal"]
        assert value["terminal"]["body"]["phase"] == "CANCELLED", value["terminal"]
        assert value["terminal"]["body"]["cancel_requested"] is True, value["terminal"]
        assert "Cancellation requested" in value["visible_requested"], value
        assert "Processing cancelled" in value["visible_confirmed"], value
        item = {
            "root": f"/api/v1/projects/{project_id}",
            "analysis_id": analysis_id,
            "dataset_id": fixture["dataset_id"],
            "context_revision_id": fixture["context_revision_id"],
        }
        progress = self.progress(client, item["root"], analysis_id)
        self.check_progress_identity(progress, project_id, item)
        assert progress["status"] == "FAILED", progress
        assert progress["phase"] == "CANCELLED", progress
        assert progress["cancel_requested"] is True, progress
        assert progress["lease_until"] is None, progress
        detail = client.get(
            item["root"] + f"/netflow-analyses/{analysis_id}"
        )
        detail.raise_for_status()
        detail_value = detail.json()
        assert detail_value["status"] == "FAILED", detail_value
        assert detail_value["can_read_result"] is False, detail_value
        assert detail_value["result"] is None, detail_value
        observations = client.get(
            item["root"] + f"/netflow-analyses/{analysis_id}/observations",
            params={"limit": 1},
        )
        assert observations.status_code == 409, (
            observations.status_code,
            observations.text,
        )
        sql = self.bulk_sql(analysis_id)
        self.write_json(self.evidence / "progress-active-cancel-sql.json", sql)
        assert sql["analysis_status"] == "FAILED", sql
        assert sql["phase"] == "CANCELLED", sql
        assert sql["cancel_requested"] is True, sql
        assert sql["lease_until"] is None, sql
        assert sql["files_completed"] <= sql["files_total"], sql
        current_after = self.current(client, project_id)
        assert current_after["current"] is not None, current_after
        assert current_after["current"]["analysis_id"] == prior_success, current_after
        assert (
            current_after["latest_attempt"]["analysis_id"] == analysis_id
        ), current_after
        result = {
            "analysis_id": analysis_id,
            "dataset_id": fixture["dataset_id"],
            "input_bytes": fixture["input_bytes"],
            "attempts_path": "ui-cancel-attempts/",
            "attempts": value["attempts"],
            "start": value["start"],
            "live_lease": value["live_lease"],
            "ack": value["ack"],
            "requested_visible": value["visible_requested"],
            "terminal": progress_sample(progress),
            "terminal_visible": value["visible_confirmed"],
            "current_while_running": value["current_while_running_analysis_id"],
            "current_after_cancel": current_after["current"]["analysis_id"],
            "latest_attempt": current_after["latest_attempt"]["analysis_id"],
            "detail_status": detail_value["status"],
            "detail_result": detail_value["result"],
            "observations_status": observations.status_code,
            "sql_readback": sql,
        }
        self.write_json(self.evidence / "progress-active-cancel.json", result)
        return result

    def assert_terminal_ui(self, ui):
        value = ui.get("ui-terminal")
        if not value or value.get("status") != "PASS":
            raise RuntimeError("real terminal UI evidence is missing")
        assert value["route_interception"] is False, value
        assert value["analyses"], value
        return value

    # ---- scenario orchestration -------------------------------------------
    def verify_progress(self, client, project_id, report):
        small, small_id = self.small_success(client, project_id)
        report["progress_success"] = {
            "analysis_id": small["analysis_id"],
            "rows": small["input"]["rows"],
            "terminal": small["terminal"],
            "sql_readback": small["sql_readback"],
            "samples_path": small["samples_path"],
        }
        self.write_json(self.evidence / "runtime-result.json", report)

        preclaim = self.preclaim_cancel(client, project_id, small_id)
        current = self.current(client, project_id)
        assert current["current"] is not None, current
        prior_success = current["current"]["analysis_id"]
        report["preclaim_cancellation"] = {
            "status": preclaim["status"],
            "attempts": len(preclaim["attempts"]),
            "current_analysis_id": prior_success,
        }
        self.write_json(self.evidence / "runtime-result.json", report)

        success_item = self.dataset(
            client,
            project_id,
            "ui-progress-success",
            UI_SUCCESS_BYTES,
            UI_SUCCESS_FILES,
            912,
            start=False,
        )
        cancel_items = [
            self.dataset(
                client,
                project_id,
                f"ui-cancel-{label}",
                size,
                4,
                920 + number,
                start=False,
            )
            for number, (size, label) in enumerate(UI_CANCEL_SIZES)
        ]
        success = self.ui_fixture(success_item, "ui-64mb", UI_SUCCESS_BYTES)
        cancel = [
            self.ui_fixture(item, label, size)
            for item, (size, label) in zip(cancel_items, UI_CANCEL_SIZES)
        ]
        terminal = [
            {"label": "small-4mb", "analysis_id": small_id},
        ]
        report["ui_calibration"] = {
            "success_input_bytes": UI_SUCCESS_BYTES,
            "success_files": UI_SUCCESS_FILES,
            "cancel_inputs": [
                {"label": label, "input_bytes": size}
                for size, label in UI_CANCEL_SIZES
            ],
            "reason": (
                "64 MB gives the browser 5-second progress interval an unfinished "
                "first observation and a later terminal observation; the cancellation "
                "window uses the reviewed 16 MB then bounded 64 MB retry. No worker "
                "sleep or timeout was changed."
            ),
        }
        self.write_json(self.evidence / "runtime-result.json", report)

        ui = self.browser(project_id, success, cancel, terminal)
        ui_success = self.assert_ui_success(client, project_id, ui, prior_success)
        report["ui_success"] = {
            "analysis_id": ui_success["analysis_id"],
            "terminal": ui_success["terminal"],
            "current_while_running": ui_success[
                "current_while_running_analysis_id"
            ],
            "current_at_success": ui_success["current_at_success"],
            "visible_first": ui_success["visible_first"],
            "visible_terminal": ui_success["visible_terminal"],
            "sql_readback": ui_success["sql_readback"],
        }
        self.write_json(self.evidence / "runtime-result.json", report)
        active = self.assert_ui_cancel(client, project_id, ui)
        report["active_cancellation"] = active
        self.write_json(self.evidence / "runtime-result.json", report)
        report["ui"] = {
            "success": {
                "analysis_id": ui_success["analysis_id"],
                "terminal": ui_success["terminal"],
                "current_while_running": ui_success[
                    "current_while_running_analysis_id"
                ],
                "current_at_success": ui_success["current_at_success"],
            },
            "cancel": {
                "analysis_id": active["analysis_id"],
                "input_bytes": active["input_bytes"],
                "requested_visible": active["requested_visible"],
                "terminal_visible": active["terminal_visible"],
                "current_after_cancel": active["current_after_cancel"],
            },
            "terminal_views": self.assert_terminal_ui(ui),
        }
        self.write_json(self.evidence / "runtime-result.json", report)

    def verify_capacity(self, client, project_id, report):
        capacity, capacity_id = self.capacity(client, project_id)
        report.update(
            {
                "input": capacity["input"],
                "analysis_id": capacity["analysis_id"],
                "status": capacity["status"],
                "quality": capacity["quality"],
                "error_code": capacity["error_code"],
                "seconds": capacity["seconds"],
                "observation_count": capacity["observation_count"],
                "peer_count": capacity["peer_count"],
            }
        )
        self.write_json(self.evidence / "runtime-result.json", report)

        preclaim = self.preclaim_cancel(client, project_id, capacity_id)
        current = self.current(client, project_id)
        assert current["current"] is not None, current
        prior_success = current["current"]["analysis_id"]
        report["preclaim_cancellation"] = {
            "status": preclaim["status"],
            "attempts": len(preclaim["attempts"]),
            "current_analysis_id": prior_success,
        }
        self.write_json(self.evidence / "runtime-result.json", report)

        cancel_items = [
            self.dataset(
                client,
                project_id,
                f"capacity-cancel-{label}",
                size,
                4,
                930 + number,
                start=False,
            )
            for number, (size, label) in enumerate(UI_CANCEL_SIZES)
        ]
        cancel = [
            self.ui_fixture(item, label, size)
            for item, (size, label) in zip(cancel_items, UI_CANCEL_SIZES)
        ]
        terminal = [
            {"label": "capacity-128mb", "analysis_id": capacity_id},
        ]
        self.write_json(self.evidence / "runtime-result.json", report)

        ui = self.browser(project_id, None, cancel, terminal)
        active = self.assert_ui_cancel(client, project_id, ui)
        report["active_cancellation"] = active
        self.write_json(self.evidence / "runtime-result.json", report)

        terminal_ui = self.assert_terminal_ui(ui)
        current = self.current(client, project_id)
        assert current["current"] is not None, current
        assert (
            current["current"]["analysis_id"] == active["current_after_cancel"]
        ), current
        report["ui"] = {
            "cancel": {
                "analysis_id": active["analysis_id"],
                "input_bytes": active["input_bytes"],
                "requested_visible": active["requested_visible"],
                "terminal_visible": active["terminal_visible"],
                "current_after_cancel": active["current_after_cancel"],
            },
            "terminal_views": terminal_ui,
        }
        self.write_json(self.evidence / "runtime-result.json", report)

    def verify(self):
        with httpx.Client(
            base_url=f"http://127.0.0.1:{self.v['API_PORT']}", timeout=30
        ) as client:
            login = client.post(
                "/api/v1/login/access-token",
                data={
                    "username": self.v["FIRST_SUPERUSER"],
                    "password": self.v["FIRST_SUPERUSER_PASSWORD"],
                },
            )
            login.raise_for_status()
            token = login.json()["access_token"]
            client.headers["Authorization"] = f"Bearer {token}"
            project = client.post(
                "/api/v1/projects/",
                json={"name": "Synthetic bulk runtime acceptance"},
            )
            project.raise_for_status()
            project_id = project.json()["id"]
            report = {
                "scope": "real agent-compose / Linux arm64 guest / PostgreSQL / HTTP / UI",
                "scenario": self.scenario,
                "build": self.sha,
                "project_id": project_id,
                "TB_acceptance": "TB 验收未执行",
                "owned_evidence": {
                    "container_logs": "logs/",
                    "controller_data": "controller-data/",
                    "snapshots": "snapshots/",
                    "cleanup": "cleanup.json",
                },
            }
            self.write_json(self.evidence / "runtime-result.json", report)
            if self.scenario in ("progress", "all"):
                self.verify_progress(client, project_id, report)
            if self.scenario in ("capacity", "all"):
                self.verify_capacity(client, project_id, report)
            self.check_identity()
            report["status"] = "PASS"
            self.write_json(self.evidence / "runtime-result.json", report)

    # ---- failure persistence and explicit cleanup -------------------------
    def persist_failure(self, error, trace):
        self.evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.evidence / "runtime-result.json"
        report = {}
        if path.exists():
            try:
                report = json.loads(path.read_text())
            except json.JSONDecodeError:
                report = {}
        report.setdefault("build", self.sha)
        report.setdefault("scenario", self.scenario)
        report["status"] = "FAIL"
        report["error"] = str(error)
        if trace:
            report["traceback"] = trace
        self.write_json(path, report)

    def _container_record(self, target):
        completed = subprocess.run(
            ["docker", "inspect", target],
            env=self.environment,
            text=True,
            capture_output=True,
        )
        if completed.returncode:
            return {
                "target": target,
                "inspect_error": (completed.stderr or completed.stdout).strip(),
            }
        values = json.loads(completed.stdout)
        if not values:
            return {"target": target, "inspect_error": "no inspect result"}
        value = values[0]
        return {
            "id": value.get("Id"),
            "name": str(value.get("Name", "")).lstrip("/"),
            "status": value.get("State", {}).get("Status"),
            "image": value.get("Config", {}).get("Image"),
            "mounts": [
                mount.get("Source") for mount in value.get("Mounts", []) if mount
            ],
        }

    def _guest_containers(self):
        try:
            identifiers = subprocess.check_output(
                [
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    f"ancestor={self.v['RUNNER_IMAGE']}",
                ],
                env=self.environment,
                text=True,
            ).split()
        except (OSError, subprocess.CalledProcessError):
            return []
        guests = []
        for identifier in identifiers:
            record = self._container_record(identifier)
            if any(
                str(mount).startswith(str(self.evidence) + "/")
                for mount in record.get("mounts", [])
            ):
                record["guest"] = True
                guests.append(record)
        return guests

    def _capture_container_logs(self, target, record, logs):
        safe = target.replace("/", "_")
        path = logs / f"{safe}.log"
        with path.open("wb") as stream:
            completed = subprocess.run(
                ["docker", "logs", target],
                env=self.environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
        record["log"] = str(path.relative_to(self.evidence))
        record["log_exit"] = completed.returncode

    def _remove(self, target):
        completed = subprocess.run(
            ["docker", "rm", "-fv", target],
            env=self.environment,
            text=True,
            capture_output=True,
        )
        return {
            "target": target,
            "exit": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }

    def _readback(self):
        result = {"errors": []}
        for key, command in (
            (
                "containers",
                [
                    "docker",
                    "ps",
                    "-a",
                    "--format",
                    "{{.ID}}|{{.Names}}|{{.Status}}",
                    "--filter",
                    f"name={self.network}",
                ],
            ),
            (
                "networks",
                [
                    "docker",
                    "network",
                    "ls",
                    "--format",
                    "{{.ID}}|{{.Name}}",
                    "--filter",
                    f"name={self.network}",
                ],
            ),
        ):
            completed = subprocess.run(
                command, env=self.environment, text=True, capture_output=True
            )
            if completed.returncode:
                result["errors"].append(
                    {
                        "readback": key,
                        "exit": completed.returncode,
                        "stderr": completed.stderr.strip(),
                    }
                )
                result[key] = []
            else:
                result[key] = [
                    line.split("|") for line in completed.stdout.splitlines() if line
                ]
        guests = self._guest_containers()
        result["guests"] = [
            {"id": guest.get("id"), "name": guest.get("name")} for guest in guests
        ]
        containers = result.get("containers", [])
        leftovers = [
            row for row in containers if len(row) > 1 and row[1].startswith(self.network)
        ]
        networks = [
            row for row in result.get("networks", []) if len(row) > 1 and row[1] == self.network
        ]
        if guests:
            leftovers.extend(
                {"guest": guest.get("id"), "name": guest.get("name")}
                for guest in guests
            )
        if networks:
            leftovers.extend({"network": row[1]} for row in networks)
        result["leftovers"] = leftovers
        return result

    def finish(self):
        if self._cleanup is not None:
            return self._cleanup
        try:
            return self._finish()
        except Exception as error:
            self._cleanup = {
                "status": "FAIL",
                "error": str(error),
                "note": "cleanup aborted before readback; see harness log",
            }
            self.write_json(self.evidence / "cleanup.json", self._cleanup)
            return self._cleanup

    def _finish(self):
        logs = self.evidence / "logs"
        logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        host_processes = []
        for index, process in enumerate(self.procs):
            if process.poll() is None:
                process.terminate()
        for index, process in enumerate(self.procs):
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(5)
                except subprocess.TimeoutExpired:
                    pass
            host_processes.append(
                {"index": index, "pid": process.pid, "returncode": process.returncode}
            )

        containers = []
        for target in list(self.names):
            record = self._container_record(target)
            record["owned"] = "named"
            containers.append(record)
        guests = self._guest_containers()
        for record in guests:
            record["owned"] = "guest"
            containers.append(record)
        for record in containers:
            target = record.get("id") or record.get("target")
            if target:
                self._capture_container_logs(target, record, logs)
        self.write_json(self.evidence / "containers-before-cleanup.json", containers)

        removals = []
        for record in guests:
            if record.get("id"):
                removals.append(self._remove(record["id"]))
        for target in reversed(self.names):
            removals.append(self._remove(target))
        network_removal = subprocess.run(
            ["docker", "network", "rm", self.network],
            env=self.environment,
            text=True,
            capture_output=True,
        )
        network = {
            "target": self.network,
            "exit": network_removal.returncode,
            "stdout": network_removal.stdout.strip(),
            "stderr": network_removal.stderr.strip(),
        }
        readback = self._readback()
        readback_ok = (
            not readback["errors"]
            and not readback["leftovers"]
        )
        cleanup = {
            "status": "PASS" if readback_ok else "FAIL",
            "idempotent": True,
            "network": self.network,
            "host_processes": host_processes,
            "containers": containers,
            "removals": removals,
            "network_removal": network,
            "logs": str(logs.relative_to(self.evidence)),
            "readback": readback,
            "note": "cleanup status is decided by docker ps/network ls/inspect readback, not rm exit codes alone",
        }
        self._cleanup = cleanup
        self.write_json(self.evidence / "cleanup.json", cleanup)
        return cleanup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument(
        "--scenario",
        choices=("capacity", "progress", "small", "all"),
        default="capacity",
    )
    args = parser.parse_args()
    scenario = "progress" if args.scenario == "small" else args.scenario
    evidence = args.evidence.resolve()
    if evidence.exists():
        raise SystemExit("Use a new evidence directory")
    run = Run(Path(__file__).resolve().parents[1], evidence, scenario)
    failure = False
    try:
        run.check_identity()
        run.prep()
        run.infra()
        run.host()
        run.verify()
    except Exception as error:
        failure = True
        run.persist_failure(error, traceback.format_exc())
    try:
        cleanup = run.finish()
    except Exception as error:
        cleanup = {"status": "FAIL", "error": str(error)}
    if not failure and cleanup.get("status") != "PASS":
        failure = True
        run.persist_failure(
            RuntimeError("cleanup readback did not pass; see cleanup.json"), ""
        )
    if not failure and cleanup.get("status") == "PASS":
        report_path = evidence / "runtime-result.json"
        report = json.loads(report_path.read_text())
        report["cleanup_status"] = cleanup.get("status")
        report["cleanup_path"] = "cleanup.json"
        run.write_json(report_path, report)
    if failure:
        sys.stderr.write(f"FAIL evidence={evidence}\n")
        return 1
    sys.stdout.write(
        json.dumps(
            {"status": "PASS", "report": str(evidence / "runtime-result.json")}
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
