"""HTTP lifecycle contracts backed by the real fixed processor and PostgreSQL."""

import hashlib
import io
import json
import stat
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlmodel import Session

from app.core.config import settings
from app.domain.models import Artifact, NetFlowDataset
from app.domain.netflow_models import NetFlowAnalysis, NetFlowContextRevision
from app.integrations import netflow_processor as processor
from app.integrations.agent_compose import AgentComposeSessionObservation as Observation
from tests.api.routes.test_netflow_datasets import _member, _upload
from tests.utils.netflow_processing import (
    context_request,
    execute,
    prepared_dataset,
    published_analysis,
    reserve,
)

HEADER = "IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
VALID = "192.0.2.1,198.51.100.1,6,443,51000\n"
INVALID = "not-an-ip,198.51.100.1,6,443,51000\n"


@pytest.fixture
def setup(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    return prepared_dataset(client, db, superuser_token_headers, tmp_path, monkeypatch)


def _url(setup: dict[str, Any], analysis_id: str) -> str:
    return f"{setup['root']}/netflow-analyses/{analysis_id}"


def _get(client: TestClient, setup: dict[str, Any], analysis_id: str) -> dict[str, Any]:
    response = client.get(_url(setup, analysis_id), headers=setup["headers"])
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    value: dict[str, Any] = response.json()
    return value


def _reconcile(
    client: TestClient, setup: dict[str, Any], analysis_id: str, key: str
) -> dict[str, Any]:
    response = client.post(
        _url(setup, analysis_id) + "/reconcile",
        headers=setup["headers"] | {"Idempotency-Key": key},
    )
    assert response.status_code == 200, response.text
    value: dict[str, Any] = response.json()
    return value


def _retry_denied(client: TestClient, setup: dict[str, Any], analysis_id: str) -> None:
    response = client.post(
        setup["dataset_url"] + "/analyses",
        headers=setup["headers"] | {"Idempotency-Key": str(uuid.uuid4())},
        json={
            "context_revision_id": setup["context_revision_id"],
            "retry_of_analysis_id": analysis_id,
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "netflow_retry_not_allowed"


@pytest.mark.parametrize("roles", [["viewer"], ["approver"], ["operator"]])
def test_context_admin_parent_key_and_revocation(
    client: TestClient, db: Session, setup: dict[str, Any], roles: list[str]
) -> None:
    headers = _member(client, setup["headers"], setup["project_id"], roles)
    url = setup["dataset_url"] + "/processing-contexts"
    body = context_request(setup["context_revision_id"], state="REVOKED")
    denied = client.post(
        url, headers=headers | {"Idempotency-Key": "revoke"}, json=body
    )
    assert denied.status_code == 403, denied.text
    stale = client.post(
        url,
        headers=setup["headers"] | {"Idempotency-Key": "stale"},
        json=context_request(),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "netflow_revision_conflict"
    changed_key = client.post(
        url, headers=setup["headers"] | {"Idempotency-Key": "context"}, json=body
    )
    assert changed_key.status_code == 409
    assert changed_key.json()["detail"]["code"] == "netflow_key_conflict"
    queued = reserve(client, setup)
    execute(db, setup, queued["analysis_id"])
    revoked = client.post(
        url, headers=setup["headers"] | {"Idempotency-Key": "revoke"}, json=body
    )
    assert revoked.status_code == 201, revoked.text
    history = client.get(url, headers=headers)
    assert history.status_code == 200
    assert {row["state"] for row in history.json()["data"]} == {"CONFIRMED", "REVOKED"}
    assert all(row["current_state"] == "REVOKED" for row in history.json()["data"])
    for suffix in ("", "/review-tasks", "/feedback", "/peers"):
        response = client.get(
            _url(setup, queued["analysis_id"]) + suffix, headers=headers
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "netflow_context_revoked"
    blocked = client.post(
        setup["dataset_url"] + "/analyses",
        headers=setup["headers"] | {"Idempotency-Key": "after-revoke"},
        json={"context_revision_id": setup["context_revision_id"]},
    )
    assert blocked.status_code == 409
    assert len(setup["control"].starts) == 1


def test_real_success_seals_blank_feedback_and_provenance(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = published_analysis(
        client, db, superuser_token_headers, tmp_path, monkeypatch
    )
    analysis = value["analysis"]
    dataset = db.get(NetFlowDataset, uuid.UUID(value["dataset_id"]))
    assert dataset is not None
    provenance = analysis["provenance"]
    assert provenance["dataset"]["raw_sha256"] == dataset.raw_sha256
    assert provenance["dataset"]["normalized_sha256"] == dataset.normalized_sha256
    assert provenance["component"] == processor.COMPONENT_IDENTITY
    assert provenance["runner_build_version"] == "synthetic-nf273"
    assert analysis["result"]["counts"]["valid_records"] == 8
    assert analysis["test_fixture"] is True
    feedback = client.get(
        _url(value, value["analysis_id"]) + "/feedback",
        headers=superuser_token_headers,
        params={"feedback_revision_id": value["feedback_revision_id"]},
    )
    assert feedback.status_code == 200, feedback.text
    original = feedback.json()
    assert original["system_generated"] and original["authenticated_actor_id"] is None
    assert all(
        all(answer is None for answer in row["answers"].values())
        and row["provided_by"] is None
        for row in original["submission"]["responses"]
    )
    before = analysis["result"]
    assert (
        reserve(client, value, key="ordinary-repeat")["analysis_id"]
        == value["analysis_id"]
    )
    _retry_denied(client, value, value["analysis_id"])
    execute(db, value, value["analysis_id"])
    assert _get(client, value, value["analysis_id"])["result"] == before
    assert len(value["control"].starts) == 1


@pytest.mark.parametrize(
    ("raw", "valid", "isolated"),
    [(HEADER, 0, 0), (HEADER + INVALID, 0, 1), (HEADER + VALID + INVALID, 1, 1)],
)
def test_empty_all_isolated_and_partial_are_distinct(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    valid: int,
    isolated: int,
) -> None:
    value = prepared_dataset(
        client, db, superuser_token_headers, tmp_path, monkeypatch, raw_text=raw
    )
    queued = reserve(client, value)
    execute(db, value, queued["analysis_id"])
    result = _get(client, value, queued["analysis_id"])
    assert result["quality"]["activity_valid_record_count"] == valid
    assert result["quality"]["isolated_record_count"] == isolated
    assert result["quality"]["raw_record_count"] == valid + isolated
    if isolated and not valid:
        assert (
            result["status"] == "FAILED"
            and result["error_code"] == "netflow_no_valid_records"
        )
        assert result["result"] is None and result["feedback_revision_id"] is None
    else:
        assert (
            result["pipeline_complete"] and result["feedback_revision_id"] is not None
        )
        assert result["result"]["counts"]["valid_records"] == valid
        if isolated:
            assert result["status"] == "SUCCEEDED_WITH_WARNINGS"
        else:
            assert result["result"]["input_state"] == "empty"


def test_current_result_uses_confirmed_collection_scope_and_pins_success(
    client: TestClient, db: Session, setup: dict[str, Any]
) -> None:
    revised = client.post(
        setup["dataset_url"] + "/processing-contexts",
        headers=setup["headers"] | {"Idempotency-Key": "collection-scope"},
        json=context_request(
            setup["context_revision_id"], collection_scope="branch-edge-a"
        ),
    )
    assert revised.status_code == 201, revised.text
    setup["context_revision_id"] = revised.json()["context_revision_id"]
    queued = reserve(client, setup, key="scoped-analysis")
    execute(db, setup, queued["analysis_id"])
    response = client.get(setup["root"] + "/netflow-results/current", headers=setup["headers"])
    assert response.status_code == 200, response.text
    current = response.json()
    assert response.headers["Cache-Control"] == "private, no-store"
    assert current["scope_id"] == "synthetic-nf273:branch-edge-a"
    assert current["current"]["analysis_id"] == queued["analysis_id"]
    assert current["latest_attempt"]["analysis_id"] == queued["analysis_id"]


def test_current_result_does_not_turn_failed_attempt_into_empty_result(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = prepared_dataset(
        client,
        db,
        superuser_token_headers,
        tmp_path,
        monkeypatch,
        raw_text=HEADER + INVALID,
    )
    revised = client.post(
        setup["dataset_url"] + "/processing-contexts",
        headers=setup["headers"] | {"Idempotency-Key": "collection-scope"},
        json=context_request(
            setup["context_revision_id"], collection_scope="branch-edge-a"
        ),
    )
    assert revised.status_code == 201, revised.text
    setup["context_revision_id"] = revised.json()["context_revision_id"]
    queued = reserve(client, setup, key="scoped-failure")
    row = execute(db, setup, queued["analysis_id"])
    assert row.status == "FAILED"
    response = client.get(setup["root"] + "/netflow-results/current", headers=setup["headers"])
    assert response.status_code == 200, response.text
    current = response.json()
    assert current["current"] is None
    assert current["latest_attempt"]["status"] == "FAILED"


def test_current_result_keeps_prior_success_when_newer_same_scope_dataset_fails(
    client: TestClient, db: Session, setup: dict[str, Any]
) -> None:
    first_context = client.post(
        setup["dataset_url"] + "/processing-contexts",
        headers=setup["headers"] | {"Idempotency-Key": "scope-first"},
        json=context_request(
            setup["context_revision_id"], collection_scope="branch-edge-a"
        ),
    )
    assert first_context.status_code == 201, first_context.text
    setup["context_revision_id"] = first_context.json()["context_revision_id"]
    success = reserve(client, setup, key="scope-success")
    execute(db, setup, success["analysis_id"])
    uploaded = _upload(
        client,
        setup["headers"],
        setup["project_id"],
        (HEADER + INVALID).encode(),
    )
    assert uploaded.status_code == 201, uploaded.text
    failed_setup = setup | {
        "dataset_id": uploaded.json()["id"],
        "dataset_url": setup["root"] + "/netflow-datasets/" + uploaded.json()["id"],
        "context_revision_id": None,
    }
    newer_context = client.post(
        failed_setup["dataset_url"] + "/processing-contexts",
        headers=setup["headers"] | {"Idempotency-Key": "scope-newer"},
        json=context_request(collection_scope="branch-edge-a"),
    )
    assert newer_context.status_code == 201, newer_context.text
    failed_setup["context_revision_id"] = newer_context.json()["context_revision_id"]
    failed = reserve(client, failed_setup, key="scope-failure")
    row = execute(db, failed_setup, failed["analysis_id"])
    assert row.status == "FAILED"
    response = client.get(setup["root"] + "/netflow-results/current", headers=setup["headers"])
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["current"]["analysis_id"] == success["analysis_id"]
    assert value["latest_attempt"]["analysis_id"] == failed["analysis_id"]


def test_current_result_scans_past_101_newer_failed_attempts(
    client: TestClient, db: Session, setup: dict[str, Any]
) -> None:
    context = client.post(
        setup["dataset_url"] + "/processing-contexts",
        headers=setup["headers"] | {"Idempotency-Key": "scope-first"},
        json=context_request(
            setup["context_revision_id"], collection_scope="branch-edge-a"
        ),
    )
    assert context.status_code == 201, context.text
    setup["context_revision_id"] = context.json()["context_revision_id"]
    success = reserve(client, setup, key="scope-success")
    published = execute(db, setup, success["analysis_id"])
    for index in range(101):
        db.add(
            NetFlowAnalysis(
                tenant_id=published.tenant_id,
                project_id=published.project_id,
                dataset_id=published.dataset_id,
                context_revision_id=published.context_revision_id,
                network_namespace=published.network_namespace,
                processing_identity_sha256=f"{index + 1:064x}",
                identity=published.identity,
                request=published.request,
                quality=published.quality,
                test_fixture=published.test_fixture,
                created_by=published.created_by,
                status="PENDING",
                agent_run_id=f"{index + 1000:064x}",
                agent_project_id=published.agent_project_id,
                runner_build_version=published.runner_build_version,
                created_at=published.created_at + timedelta(seconds=index + 1),
            )
        )
    db.commit()
    response = client.get(setup["root"] + "/netflow-results/current", headers=setup["headers"])
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["current"]["analysis_id"] == success["analysis_id"]
    assert value["latest_attempt"]["status"] == "PENDING"


def test_lost_start_response_never_reexecutes_for_same_or_new_key(
    client: TestClient, db: Session, setup: dict[str, Any]
) -> None:
    control = setup["control"]
    control.lose_start_response = True
    first = reserve(client, setup)
    assert first["status"] == "UNKNOWN" and first["result"] is None
    for key in ("analysis", "another-key"):
        assert reserve(client, setup, key=key)["analysis_id"] == first["analysis_id"]
    recovered = client.get(
        setup["dataset_url"] + "/analyses/operations/analysis", headers=setup["headers"]
    )
    assert (
        recovered.status_code == 200
        and recovered.json()["analysis_id"] == first["analysis_id"]
    )
    _retry_denied(client, setup, first["analysis_id"])
    assert len(control.starts) == 1
    execute(db, setup, first["analysis_id"])
    assert _get(client, setup, first["analysis_id"])["pipeline_complete"]
    assert len(control.starts) == 1


@pytest.mark.parametrize("missing", [False, True])
def test_original_session_terminal_reconcile_requires_complete_artifacts(
    client: TestClient, db: Session, setup: dict[str, Any], missing: bool
) -> None:
    queued = reserve(client, setup)
    control = setup["control"]
    control.lose_publication_observation = True
    row = execute(db, setup, queued["analysis_id"])
    assert row.status == "UNKNOWN" and row.result is None
    output = settings.ARTIFACT_ROOT / row.request["output_key"]
    original = (output / "analysis/manifest.json").read_bytes()
    for observation in (Observation.RUNNING, Observation.UNKNOWN):
        control.observe(row, observation)
        recovered = _reconcile(client, setup, queued["analysis_id"], observation.value)
        assert recovered["result"] is None and not recovered["pipeline_complete"]
        _retry_denied(client, setup, queued["analysis_id"])
    if missing:
        (output / "review/review-tasks.jsonl").unlink()
    control.observe(row, Observation.TERMINAL)
    terminal = _reconcile(client, setup, queued["analysis_id"], "terminal")
    if missing:
        assert terminal["status"] == "FAILED" and terminal["result"] is None
        assert terminal["feedback_revision_id"] is None
    else:
        assert (
            terminal["pipeline_complete"]
            and terminal["feedback_revision_id"] is not None
        )
        assert (output / "analysis/manifest.json").read_bytes() == original
    assert len(control.starts) == 1
    db.expire_all()
    restored = db.get(NetFlowAnalysis, row.id)
    assert (
        restored is not None
        and restored.session_id == control.runs[row.agent_run_id].session_id
    )
    db.commit()


def test_failed_identity_needs_explicit_unique_successor(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = prepared_dataset(
        client,
        db,
        superuser_token_headers,
        tmp_path,
        monkeypatch,
        raw_text=HEADER + INVALID,
    )
    parent = reserve(client, value)
    row = execute(db, value, parent["analysis_id"])
    assert row.status == "FAILED"
    assert (
        reserve(client, value, key="ordinary-new-key")["analysis_id"]
        == parent["analysis_id"]
    )
    _retry_denied(client, value, parent["analysis_id"])
    value["control"].observe(row, Observation.TERMINAL)
    child = reserve(client, value, key="retry", retry=parent["analysis_id"])
    assert child["analysis_id"] != parent["analysis_id"]
    assert child["retry_of_analysis_id"] == parent["analysis_id"]
    for key in ("retry", "retry-again"):
        assert (
            reserve(client, value, key=key, retry=parent["analysis_id"])["analysis_id"]
            == child["analysis_id"]
        )
    child_row = execute(db, value, child["analysis_id"])
    assert (
        child_row.session_id != row.session_id
        and child_row.agent_run_id != row.agent_run_id
    )
    assert _get(client, value, parent["analysis_id"])["status"] == "FAILED"
    assert len(value["control"].starts) == 2


def test_published_artifact_corruption_fails_closed(
    client: TestClient, db: Session, setup: dict[str, Any]
) -> None:
    queued = reserve(client, setup)
    row = execute(db, setup, queued["analysis_id"])
    assert row.result is not None
    root = settings.ARTIFACT_ROOT / row.result["artifacts"]["root"]
    path = root / "analysis/observations.jsonl"
    path.chmod(0o600)
    path.write_bytes(path.read_bytes() + b"{}\n")
    for suffix in ("", "/peers", "/review-tasks", "/feedback"):
        response = client.get(
            _url(setup, queued["analysis_id"]) + suffix, headers=setup["headers"]
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "netflow_artifact_integrity_failed"
    assert len(setup["control"].starts) == 1


def _import_fixture(
    db: Session, setup: dict[str, Any], tmp_path: Path, *, feedback: bool = False
) -> tuple[processor.ProcessorBundle, dict[str, Any]]:
    dataset = db.get(NetFlowDataset, uuid.UUID(setup["dataset_id"]))
    assert dataset is not None
    canonical = db.get(Artifact, dataset.normalized_artifact_id)
    assert canonical is not None
    context = db.get(NetFlowContextRevision, uuid.UUID(setup["context_revision_id"]))
    assert context is not None
    original_context = context.payload["component_context"] | {
        "tenant_id": "synthetic-original-tenant",
        "project_id": "synthetic-original-project",
        "dataset_id": "synthetic-original-dataset",
    }
    config = processor.default_config()
    bundle = processor.process(
        settings.ARTIFACT_ROOT / canonical.storage_key,
        context=original_context,
        config=config,
        output_dir=tmp_path / str(uuid.uuid4()),
        allow_test=True,
    )
    if feedback:
        blank = processor.load_feedback(
            bundle.root / "initial-feedback",
            namespace=setup["namespace"],
            allow_test=True,
        )
        processor.review_feedback_patch(
            bundle,
            blank,
            [
                {
                    "task_id": bundle.tasks[0]["task_id"],
                    "provided_by": "Synthetic original provider",
                    "submitted_at": "2026-01-01T00:00:00Z",
                    "answers": {},
                    "note_checks": [],
                }
            ],
            output_dir=bundle.root / "feedback",
            allow_test=True,
        )
    db.commit()
    return bundle, {
        "context_revision_id": setup["context_revision_id"],
        "source_manifest_sha256": hashlib.sha256(
            (bundle.root / "analysis/manifest.json").read_bytes()
        ).hexdigest(),
        "original_config": config,
        "binding_evidence": "Public synthetic original identity mapped explicitly to this isolated Project and Dataset.",
    }


def _zip(bundle: processor.ProcessorBundle, *, unsafe: str | None = None) -> bytes:
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
        for directory in ("analysis", "review", "feedback"):
            for path in sorted((bundle.root / directory).rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(bundle.root).as_posix())
        if unsafe == "link":
            link = zipfile.ZipInfo("feedback/submission.json")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, "../../outside")
        elif unsafe:
            archive.writestr(unsafe, b"untrusted")
    return result.getvalue()


def _import(
    client: TestClient,
    setup: dict[str, Any],
    metadata: dict[str, Any],
    content: bytes,
    *,
    key: str = "import",
) -> Response:
    response: Response = client.post(
        setup["dataset_url"] + "/analysis-imports",
        headers=setup["headers"] | {"Idempotency-Key": key},
        files={"file": ("result.zip", content, "application/zip")},
        data={"metadata": json.dumps(metadata)},
    )
    return response


@pytest.mark.parametrize("feedback", [False, True])
def test_real_import_preserves_original_bytes_and_optional_feedback(
    client: TestClient,
    db: Session,
    setup: dict[str, Any],
    tmp_path: Path,
    feedback: bool,
) -> None:
    bundle, metadata = _import_fixture(db, setup, tmp_path, feedback=feedback)
    archive = _zip(bundle)
    queued = _import(client, setup, metadata, archive)
    assert queued.status_code == 202, queued.text
    row = execute(db, setup, queued.json()["analysis_id"])
    result = _get(client, setup, str(row.id))
    assert result["pipeline_complete"], result
    assert result["result"]["component_run_id"] == bundle.manifest["run_id"]
    assert row.result is not None
    output = settings.ARTIFACT_ROOT / row.result["artifacts"]["root"]
    for name in ("analysis/manifest.json", "review/review-tasks.jsonl"):
        assert (output / name).read_bytes() == (bundle.root / name).read_bytes()
    blank = client.get(
        _url(setup, str(row.id)) + "/feedback",
        headers=setup["headers"],
        params={"feedback_revision_id": result["feedback_revision_id"]},
    )
    assert blank.status_code == 200, blank.text
    assert blank.json()["system_generated"]
    assert all(
        item["provided_by"] is None
        and all(answer is None for answer in item["answers"].values())
        for item in blank.json()["submission"]["responses"]
    )
    if feedback:
        current = client.get(
            _url(setup, str(row.id)) + "/feedback", headers=setup["headers"]
        )
        assert current.status_code == 200, current.text
        assert current.json()["feedback_revision_id"] != result["feedback_revision_id"]
        assert current.json()["submission"] == json.loads(
            (bundle.root / "feedback/submission.json").read_text()
        )
    duplicate = _import(client, setup, metadata, archive, key="new-import-key")
    assert duplicate.status_code == 202 and duplicate.json()["analysis_id"] == str(
        row.id
    )
    changed = _import(client, setup, metadata, _zip(bundle, unsafe="unknown.txt"))
    assert (
        changed.status_code == 409
        and changed.json()["detail"]["code"] == "netflow_key_conflict"
    )
    assert len(setup["control"].starts) == 1


def test_rejected_import_uploads_are_removed_without_losing_reserved_input(
    client: TestClient,
    db: Session,
    setup: dict[str, Any],
    tmp_path: Path,
) -> None:
    bundle, metadata = _import_fixture(db, setup, tmp_path)
    archive = _zip(bundle)
    setup["control"].lose_start_response = True
    queued = _import(client, setup, metadata, archive)
    assert queued.status_code == 202
    assert queued.json()["status"] == "UNKNOWN"
    imports = tmp_path / "netflow-processing" / setup["project_id"] / "imports"
    reserved = set(imports.iterdir())

    conflict = _import(
        client, setup, metadata | {"binding_evidence": "Changed evidence"}, archive
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "netflow_key_conflict"
    assert set(imports.iterdir()) == reserved

    invalid = _import(
        client, setup, metadata | {"unexpected": True}, archive, key="invalid"
    )
    assert invalid.status_code == 422
    assert set(imports.iterdir()) == reserved

    row = execute(db, setup, queued.json()["analysis_id"])
    result = _get(client, setup, str(row.id))
    assert result["pipeline_complete"]
    assert result["result"]["component_run_id"] == bundle.manifest["run_id"]


@pytest.mark.parametrize(
    "unsafe",
    [
        "malformed",
        "../escape",
        "/absolute",
        "analysis/manifest.json",
        "private.html",
        "link",
    ],
)
def test_unsafe_import_never_publishes(
    client: TestClient, db: Session, setup: dict[str, Any], tmp_path: Path, unsafe: str
) -> None:
    bundle, metadata = _import_fixture(db, setup, tmp_path)
    archive = b"not a ZIP" if unsafe == "malformed" else _zip(bundle, unsafe=unsafe)
    response = _import(client, setup, metadata, archive)
    if response.status_code == 202:
        row = execute(db, setup, response.json()["analysis_id"])
        public = _get(client, setup, str(row.id))
        assert public["status"] == "FAILED" and public["result"] is None
        assert public["feedback_revision_id"] is None
    else:
        assert response.status_code in (413, 422), response.text
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("mismatch", ["config", "context", "replay"])
def test_import_mismatched_material_never_publishes(
    client: TestClient,
    db: Session,
    setup: dict[str, Any],
    tmp_path: Path,
    mismatch: str,
) -> None:
    bundle, metadata = _import_fixture(db, setup, tmp_path)
    if mismatch == "config":
        metadata["original_config"] = metadata["original_config"] | {
            "limits": metadata["original_config"]["limits"] | {"max_records": 99999}
        }
    elif mismatch == "context":
        context = dict(bundle.manifest["analysis_context"])
        context["network_namespace"] = "synthetic-other"
        # A real alternate-namespace bundle, not a fabricated manifest.
        dataset = db.get(NetFlowDataset, uuid.UUID(setup["dataset_id"]))
        assert dataset is not None
        artifact = db.get(Artifact, dataset.normalized_artifact_id)
        assert artifact is not None
        bundle = processor.process(
            settings.ARTIFACT_ROOT / artifact.storage_key,
            context=context,
            config=processor.default_config(),
            output_dir=tmp_path / str(uuid.uuid4()),
            allow_test=True,
        )
        metadata["source_manifest_sha256"] = hashlib.sha256(
            (bundle.root / "analysis/manifest.json").read_bytes()
        ).hexdigest()
        db.commit()
    else:
        # Produce a genuine complete component bundle over different public input.
        dataset = db.get(NetFlowDataset, uuid.UUID(setup["dataset_id"]))
        assert dataset is not None
        artifact = db.get(Artifact, dataset.normalized_artifact_id)
        assert artifact is not None
        alternate = tmp_path / "alternate.csv"
        alternate.write_bytes(
            (settings.ARTIFACT_ROOT / artifact.storage_key)
            .read_bytes()
            .replace(b"50001", b"50009")
        )
        bundle = processor.process(
            alternate,
            context=bundle.manifest["analysis_context"],
            config=processor.default_config(),
            output_dir=tmp_path / str(uuid.uuid4()),
            allow_test=True,
        )
        metadata["source_manifest_sha256"] = hashlib.sha256(
            (bundle.root / "analysis/manifest.json").read_bytes()
        ).hexdigest()
        db.commit()
    response = _import(client, setup, metadata, _zip(bundle))
    if response.status_code == 202:
        row = execute(db, setup, response.json()["analysis_id"])
        public = _get(client, setup, str(row.id))
        assert public["status"] == "FAILED" and public["result"] is None
    else:
        assert response.status_code == 422, response.text


@pytest.mark.parametrize("retry", [False, True])
def test_concurrent_reservations_have_one_attempt(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    retry: bool,
) -> None:
    value = prepared_dataset(
        client,
        db,
        superuser_token_headers,
        tmp_path,
        monkeypatch,
        raw_text=HEADER + INVALID,
    )
    parent_id = None
    if retry:
        parent_id = reserve(client, value)["analysis_id"]
        parent = execute(db, value, parent_id)
        assert parent.status == "FAILED"
        value["control"].observe(parent, Observation.TERMINAL)
    # Each request uses FastAPI's real get_db dependency: separate Session and
    # transaction, while the fixture Session holds no transaction or row locks.
    db.commit()
    barrier = Barrier(2)

    def request(index: int) -> dict[str, Any]:
        barrier.wait(timeout=10)
        return reserve(client, value, key=f"concurrent-{index}", retry=parent_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request, range(2)))
    assert results[0]["analysis_id"] == results[1]["analysis_id"]
    assert results[0]["retry_of_analysis_id"] == parent_id
    assert len(value["control"].starts) == (2 if retry else 1)
    row = execute(db, value, results[0]["analysis_id"])
    assert row.status == "FAILED" and row.error_code == "netflow_no_valid_records"


def test_lost_start_terminal_without_outputs_fails_original_attempt(
    client: TestClient, db: Session, setup: dict[str, Any]
) -> None:
    setup["control"].lose_start_response = True
    queued = reserve(client, setup)
    row = db.get(NetFlowAnalysis, uuid.UUID(queued["analysis_id"]))
    assert row is not None and row.session_id is None
    setup["control"].observe(row, Observation.TERMINAL)
    db.commit()
    result = _reconcile(client, setup, queued["analysis_id"], "terminal-without-output")
    assert result["status"] == "FAILED" and result["result"] is None
    assert result["feedback_revision_id"] is None
    assert (
        reserve(client, setup, key="ordinary-terminal-repeat")["analysis_id"]
        == queued["analysis_id"]
    )
    assert len(setup["control"].starts) == 1


def test_fixture_admission_revocation_blocks_published_material(
    client: TestClient,
    db: Session,
    setup: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued = reserve(client, setup)
    execute(db, setup, queued["analysis_id"])
    monkeypatch.setattr(settings, "NETFLOW_ALLOW_TEST_FIXTURES", False)
    response = client.get(_url(setup, queued["analysis_id"]), headers=setup["headers"])
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "netflow_test_fixture_forbidden"


@pytest.mark.parametrize("committed", [False, True])
def test_import_commit_failure_preserves_only_durable_uploads(
    client: TestClient,
    db: Session,
    setup: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    committed: bool,
) -> None:
    bundle, metadata = _import_fixture(db, setup, tmp_path)
    archive = _zip(bundle)
    commit = Session.commit

    def fail_reservation(session: Session) -> None:
        reserving = any(isinstance(row, NetFlowAnalysis) for row in session.new)
        if not reserving or committed:
            commit(session)
        if reserving:
            raise RuntimeError("Reservation commit response lost")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_reservation)
        with pytest.raises(RuntimeError, match="Reservation commit response lost"):
            _import(client, setup, metadata, archive)

    recovered = client.get(
        setup["dataset_url"] + "/analysis-imports/operations/import",
        headers=setup["headers"],
    )
    imports = tmp_path / "netflow-processing" / setup["project_id"] / "imports"
    if committed:
        assert recovered.status_code == 200
        assert recovered.json()["status"] == "PENDING"
        row = db.get(NetFlowAnalysis, uuid.UUID(recovered.json()["analysis_id"]))
        assert row is not None
        receipt = settings.ARTIFACT_ROOT / row.request["import_artifacts"]["root"]
        assert (receipt / "source.zip").read_bytes() == archive
        assert set(imports.iterdir()) == {receipt}
    else:
        assert recovered.status_code == 404
        assert not list(imports.iterdir())
