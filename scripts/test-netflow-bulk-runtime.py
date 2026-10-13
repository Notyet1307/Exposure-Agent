#!/usr/bin/env python3
"""Synthetic bulk acceptance through the real agent-compose guest and HTTP API.

Reuse the existing isolated usability harness. No deployed service, source,
credential, model or production database is read or changed.
"""

import importlib.util
import json
import sys
import time
from pathlib import Path

import httpx
import yaml

module_path = Path(__file__).with_name("test-netflow-usability.py")
spec = importlib.util.spec_from_file_location("isolated_netflow_harness", module_path)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


class Run(base.Run):
    def __init__(self, repo, evidence):
        super().__init__(repo, evidence, False)
        self.snapshots = self.evidence / "snapshots"
        self.v.update(
            NETFLOW_BULK_ROOT=str(self.snapshots),
            NETFLOW_BULK_MEMORY_MB="128",
            NETFLOW_BULK_THREADS="1",
            NETFLOW_BULK_RSS_BYTES=str(768 * 1024**2),
        )
        self.v["RUNNER_IMAGE"] = f"nf-bulk-304-runner:{self.sha}"
        self.environment = base.env(self.v)

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

    def verify(self):
        from app.netflow_bulk.__main__ import generate
        from app.netflow_bulk.storage import seal

        client = httpx.Client(
            base_url=f"http://127.0.0.1:{self.v['API_PORT']}", timeout=30
        )
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
            "/api/v1/projects/", json={"name": "Synthetic bulk runtime acceptance"}
        )
        project.raise_for_status()
        project_id = project.json()["id"]
        root = f"/api/v1/projects/{project_id}"
        source = self.evidence / "input"
        input_info = generate(
            source,
            byte_target=128000000,
            files=4,
            seed=304,
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
            source_id="runtime",
        )
        registration = client.post(
            root + "/netflow-bulk/datasets",
            headers={"Idempotency-Key": "register"},
            json={"source_id": "runtime", "ready_id": ready_id},
        )
        registration.raise_for_status()
        dataset_id = registration.json()["dataset_id"]
        context = client.post(
            root + f"/netflow-datasets/{dataset_id}/processing-contexts",
            headers={"Idempotency-Key": "context"},
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
        started = time.monotonic()
        queued = client.post(
            root + f"/netflow-datasets/{dataset_id}/analyses",
            headers={"Idempotency-Key": "analysis"},
            json={"context_revision_id": context.json()["context_revision_id"]},
        )
        queued.raise_for_status()
        analysis_id = queued.json()["analysis_id"]
        while time.monotonic() - started < 600:
            response = client.get(root + f"/netflow-analyses/{analysis_id}")
            response.raise_for_status()
            value = response.json()
            if value["status"] in ("SUCCEEDED", "SUCCEEDED_WITH_WARNINGS", "FAILED"):
                break
            time.sleep(1)
        report = {
            "scope": "real agent-compose / Linux arm64 guest / PostgreSQL / HTTP",
            "build": self.sha,
            "input": input_info,
            "analysis_id": analysis_id,
            "project_id": project_id,
            "status": value["status"],
            "quality": value["quality"],
            "error_code": value["error_code"],
            "seconds": time.monotonic() - started,
            "TB_acceptance": "TB 验收未执行",
        }
        (self.evidence / "runtime-result.json").write_text(json.dumps(report, indent=2))
        assert value["status"] in ("SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"), report[
            "error_code"
        ]
        observations = client.get(
            root + f"/netflow-analyses/{analysis_id}/observations", params={"limit": 25}
        )
        observations.raise_for_status()
        assert observations.json()["raw_record_count"] > 100000
        peers = client.get(
            root + f"/netflow-analyses/{analysis_id}/peers", params={"limit": 25}
        )
        peers.raise_for_status()
        report["observation_count"] = observations.json()["total_observations"]
        report["peer_count"] = peers.json()["total_peers"]
        report["status"] = "PASS"
        (self.evidence / "runtime-result.json").write_text(json.dumps(report, indent=2))
        client.close()


def main():
    evidence = Path(sys.argv[1]).resolve()
    if evidence.exists():
        raise SystemExit("Use a new evidence directory")
    run = Run(Path(__file__).resolve().parents[1], evidence)
    try:
        run.prep()
        run.infra()
        run.host()
        run.verify()
        sys.stdout.write(
            json.dumps(
                {"status": "PASS", "report": str(evidence / "runtime-result.json")}
            )
            + "\n"
        )
    finally:
        run.finish()


if __name__ == "__main__":
    main()
