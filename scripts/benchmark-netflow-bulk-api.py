# ruff: noqa: E402
"""Synthetic, isolated PG/API/worker benchmark. Run from backend with uv.

The actual engine and database run; only the agent-compose control plane is a
fixture. This command never connects to a deployed application or model.
"""

import argparse
import json
import statistics
import sys
import subprocess
import os
import time
import uuid
import tempfile
import atexit
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--input-benchmark", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
args.input_benchmark = args.input_benchmark.resolve()
args.output = args.output.resolve()
if tuple(
    os.environ.get(key)
    for key in ("ENVIRONMENT", "POSTGRES_SERVER", "POSTGRES_PORT", "POSTGRES_DB")
) != ("local", "127.0.0.1", "15434", "bulk_test"):
    raise SystemExit(
        "Explicit isolated database environment is required; dotenv is not loaded"
    )
# Settings resolves ../.env relative to cwd; use a private empty parent for both processes.
isolated_cwd = tempfile.TemporaryDirectory(prefix="nf-bulk-api-")
atexit.register(isolated_cwd.cleanup)
host_cwd = Path(isolated_cwd.name) / "host"
host_cwd.mkdir()
os.chdir(host_cwd)

from app.core.config import settings
from app.core.db import engine, init_db
from app.domain import netflow_bulk as bulk
from app.domain.models import Project
from app.domain.netflow_bulk_models import BulkJob
from app.domain.netflow_models import NetFlowAnalysis
from app.main import app
from app.netflow_bulk.storage import atomic_json, file_hash, seal
from tests.api.routes.test_netflow_datasets import _project
from tests.utils.netflow_processing import ControlPlane, context_request
from tests.utils.utils import get_superuser_token_headers

if (
    settings.ENVIRONMENT,
    settings.POSTGRES_SERVER,
    settings.POSTGRES_PORT,
    settings.POSTGRES_DB,
) != ("local", "127.0.0.1", 15434, "bulk_test"):
    raise SystemExit("Only the dedicated local bulk_test database on 15434 is admitted")
if args.output.exists():
    raise SystemExit("Output already exists")
input_report = json.loads((args.input_benchmark / "benchmark.json").read_text())
for member in input_report["input"]["files"]:
    if file_hash(args.input_benchmark / "input" / member["name"]) != member["sha256"]:
        raise SystemExit("Synthetic input changed")
args.output.mkdir(parents=True)
report = {
    "scope": "real PG/HTTP/independent worker process; agent-compose control plane simulated",
    "input_bytes": input_report["read_bytes"],
    "input_rows": input_report["parsed_rows"],
    "query_cache_definition": "cold = fresh DB connections, first query; hot = repeated queries; OS cache was not purged",
    "TB_acceptance": "TB 验收未执行",
    "status": "RUNNING",
}
patch = pytest.MonkeyPatch()
settings.ARTIFACT_ROOT = args.output / "artifacts"
settings.ARTIFACT_ROOT.mkdir()
settings.NETFLOW_BULK_ROOT = args.output / "snapshots"
settings.NETFLOW_BULK_ROOT.mkdir()
settings.NETFLOW_ALLOW_TEST_FIXTURES = True
settings.NETFLOW_BULK_MEMORY_MB = 128
settings.NETFLOW_BULK_THREADS = 1
settings.NETFLOW_BULK_RSS_BYTES = 768 * 1024**2
settings.NETFLOW_BULK_DISK_RESERVE_BYTES = 20 * 1024**3
control = ControlPlane(patch)
client = TestClient(app)
with Session(engine) as session:
    init_db(session)
headers = get_superuser_token_headers(client)
project = _project(client, headers)
project_id = str(project["id"])
root = f"/api/v1/projects/{project_id}"

with Session(engine) as session:
    model = session.get(Project, uuid.UUID(project_id))
    tenant = str(model.tenant_id)
started = time.monotonic()
ready_id, _ = seal(
    args.input_benchmark / "input",
    settings.NETFLOW_BULK_ROOT,
    tenant=tenant,
    project=project_id,
    source_id="benchmark",
    reserve_bytes=20 * 1024**3,
)
report["seal_seconds"] = time.monotonic() - started
registration = client.post(
    root + "/netflow-bulk/datasets",
    json={"source_id": "benchmark", "ready_id": ready_id},
    headers=headers | {"Idempotency-Key": "register"},
)
assert registration.status_code == 201, registration.text
dataset_id = registration.json()["dataset_id"]
context = client.post(
    root + f"/netflow-datasets/{dataset_id}/processing-contexts",
    json=context_request(collection_scope="bulk-benchmark"),
    headers=headers | {"Idempotency-Key": "context"},
)
assert context.status_code == 201, context.text
created = client.post(
    root + f"/netflow-datasets/{dataset_id}/analyses",
    json={"context_revision_id": context.json()["context_revision_id"]},
    headers=headers | {"Idempotency-Key": "analysis"},
)
assert created.status_code == 202, created.text
analysis_id = uuid.UUID(created.json()["analysis_id"])
failures = []
with Session(engine) as session:
    analysis = session.get(NetFlowAnalysis, analysis_id)
    fence = bulk.claim(session, analysis.id, analysis.agent_run_id, analysis.session_id)
    assert fence is not None
child_env = {
    key: os.environ[key]
    for key in ("PATH", "HOME", "USER", "TMPDIR")
    if key in os.environ
}
child_env.update(
    PROJECT_NAME="Isolated bulk benchmark worker",
    ENVIRONMENT="local",
    POSTGRES_SERVER="127.0.0.1",
    POSTGRES_PORT="15434",
    POSTGRES_DB="bulk_test",
    POSTGRES_USER=settings.POSTGRES_USER,
    POSTGRES_PASSWORD=settings.POSTGRES_PASSWORD,
    FIRST_SUPERUSER="fixture@example.net",
    FIRST_SUPERUSER_PASSWORD="unused-by-bulk-worker",
    NETFLOW_MAX_BYTES="52428800",
    NETFLOW_ALLOW_TEST_FIXTURES="true",
    ARTIFACT_ROOT=str(settings.ARTIFACT_ROOT),
    NETFLOW_BULK_ROOT=str(settings.NETFLOW_BULK_ROOT),
    NETFLOW_BULK_MEMORY_MB="128",
    NETFLOW_BULK_THREADS="1",
    NETFLOW_BULK_RSS_BYTES=str(768 * 1024**2),
    NETFLOW_BULK_DISK_RESERVE_BYTES=str(20 * 1024**3),
    RUNNER_BUILD_VERSION=settings.governance_runner_build_version,
    PYTHONPATH=str(Path(__file__).resolve().parents[1] / "backend"),
)
code = (
    "from sqlmodel import Session; from app.core.db import engine; from app.domain.netflow_bulk import run_engine; from app.domain import netflow_processing; from app.integrations.agent_compose import AgentComposeSessionObservation; import uuid; netflow_processing.session_observation=lambda row:(row.session_id,AgentComposeSessionObservation.RUNNING); s=Session(engine); run_engine(s,uuid.UUID('"
    + str(analysis_id)
    + "'),"
    + str(fence)
    + "); s.close()"
)
with (args.output / "worker.log").open("wb") as log:
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=host_cwd,
        env=child_env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    during = []
    while process.poll() is None:
        tick = time.monotonic()
        response = client.get(root, headers=headers)
        during.append((time.monotonic() - tick, response.status_code))
        time.sleep(0.25)
    if process.returncode:
        failures.append("worker_exit_" + str(process.returncode))
report["worker_isolation"] = (
    "separate OS process; control-plane reservation/claim simulated"
)
report["end_to_end_seconds"] = time.monotonic() - started
if failures:
    report.update(status="FAIL", errors=failures)
    atomic_json(args.output / "api-benchmark.json", report)
    raise SystemExit(1)
with Session(engine) as session:
    analysis = session.get(NetFlowAnalysis, analysis_id)
    job = session.get(BulkJob, analysis_id)
    assert analysis.status in ("SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"), analysis.status
    report["worker_metrics"] = job.metrics
    report["counts"] = analysis.result["counts"]
    report["object_count"] = analysis.result["files"]["observations"]["rows"]
    report["peer_count"] = analysis.result["files"]["peers"]["rows"]
report["project_id"], report["analysis_id"] = project_id, str(analysis_id)
# The source mount is physically absent during all result queries.
settings.NETFLOW_BULK_ROOT.rename(args.output / "offline-snapshots")
report["raw_input_available_during_queries"] = False


def summarize(values):
    ordered = sorted(values)
    return {
        "n": len(values),
        "p50_ms": statistics.median(values) * 1000,
        "p95_ms": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] * 1000,
        "max_ms": max(values) * 1000,
    }


report["api_during_processing"] = summarize([v for v, status in during]) | {
    "statuses": sorted(set(status for _, status in during))
}
for endpoint in ("observations", "peers"):
    url = root + f"/netflow-analyses/{analysis_id}/{endpoint}"
    for mode in ("cold_connection", "hot"):
        times = []
        for _ in range(20):
            if mode == "cold_connection":
                engine.dispose()
            tick = time.monotonic()
            response = client.get(url, params={"limit": 25}, headers=headers)
            times.append(time.monotonic() - tick)
            assert response.status_code == 200, response.text
            assert len(response.json()["data"]) == 25
        report[f"{endpoint}_{mode}"] = summarize(times)
failed_requests = [status for _, status in during if status != 200]
report["status"] = "FAIL" if failed_requests or not during else "PASS"
if failed_requests or not during:
    report["errors"] = ["processing_api_unavailable"]
atomic_json(args.output / "api-benchmark.json", report)
patch.undo()
client.close()
sys.stdout.write(
    json.dumps(
        {"status": report["status"], "report": str(args.output / "api-benchmark.json")}
    )
    + "\n"
)

if report["status"] != "PASS":
    raise SystemExit(1)
