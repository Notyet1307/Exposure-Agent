import hashlib
import io
import ipaddress
import logging
import re
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn, cast

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.api.deps import get_db
from app.core.config import settings
from app.core.db import engine
from app.domain import customer_ledger as ledger
from app.domain import customer_uploads
from app.domain.diagnostics import Diagnostic
from app.domain.models import (
    Artifact,
    AuditEvent,
    CustomerLedgerRevision,
    CustomerUpload,
    CustomerUploadReplacement,
    Project,
)
from app.main import app
from app.models import User
from tests.api.routes.test_customer_uploads import _create_member, _create_project
from tests.utils.audit import reject_audit_inserts
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

LedgerSetup = tuple[str, dict[str, str], dict[str, Any], bytes, Path]


@pytest.fixture
def setup_ledger(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> LedgerSetup:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    root = f"{settings.API_V1_STR}/projects/{project['id']}"
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(list(ledger.HEADERS))
    for n in range(getattr(request, "param", 61)):
        # Duplicate IPs are distinct original rows, and optional cell types survive editing.
        sheet.append(
            [
                "2001:db8:10::20",
                443,
                443,
                "是",
                "example.net",
                "HTTPS",
                "原负责人",
                "业务部",
                "端口负责人",
                datetime(2026, 1, 2, 3, 4),
                n + 1,
            ]
        )
    stream = io.BytesIO()
    book.save(stream)
    book.close()
    data = stream.getvalue()
    uploaded = client.post(
        root + "/customer-uploads",
        headers=superuser_token_headers,
        files={"file": ("original.xlsx", data)},
    )
    assert uploaded.status_code == 201, uploaded.text
    upload = uploaded.json()
    assert (
        client.post(
            root + f"/customer-uploads/{upload['id']}/select",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )
    return root, superuser_token_headers, upload, data, tmp_path


def read(client: TestClient, setup: LedgerSetup, **params: Any) -> dict[str, Any]:
    root, headers, *_ = setup
    response = client.get(root + "/customer-ledger", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def edit(
    page: dict[str, Any],
    operation: str = "update",
    fields: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return dict(
        expected_upload_id=page["upload_id"],
        expected_revision_id=page["revision_id"],
        expected_profile_id=page["current_profile_id"],
        operation=operation,
        entry_id=page["data"][0]["entry_id"],
        fields=fields or {"asset_ip": "2001:db8:10::25"},
        reason="更正录入地址",
        **extra,
    )


def post(
    client: TestClient,
    setup: LedgerSetup,
    payload: dict[str, Any],
    key: str | None = None,
) -> Any:
    root, headers, *_ = setup
    return client.post(
        root + "/customer-ledger/revisions",
        headers={**headers, "Idempotency-Key": key or str(uuid.uuid4())},
        json=payload,
    )


def test_original_pagination_edit_history_and_typed_fields(
    client: TestClient, setup_ledger: LedgerSetup
) -> None:
    first = read(client, setup_ledger)
    second = read(client, setup_ledger, upload_id=first["upload_id"], skip=25)
    assert (
        first["count"] == 61 and len(first["data"]) == 25 and first["unique_ips"] == 1
    )
    assert first["data"][0]["entry_id"] != second["data"][0]["entry_id"]
    assert first["revision_id"] is None and first["can_edit"]
    changed = post(client, setup_ledger, edit(first))
    assert changed.status_code == 201, changed.text
    current = read(client, setup_ledger)
    assert (
        current["revision_id"] == changed.json()["id"]
        and current["upload_id"] != first["upload_id"]
    )
    assert (
        current["unique_ips"] == 2
        and current["data"][0]["canonical_ip"] == "2001:db8:10::25"
    )
    assert current["data"][1]["canonical_ip"] == "2001:db8:10::20"
    assert current["data"][0]["entry_id"] == first["data"][0]["entry_id"]
    old = read(client, setup_ledger, upload_id=first["upload_id"])
    assert old["data"] == first["data"] and not old["can_edit"]
    assert (
        current["data"][0]["fields"]["department"]
        == first["data"][0]["fields"]["department"]
    )
    with Session(engine) as db:
        u = db.get(CustomerUpload, current["upload_id"])
        assert u is not None
        a = db.get(Artifact, u.artifact_id)
        assert a is not None
        path = setup_ledger[-1] / a.storage_key
        book = load_workbook(path)
        assert book.active is not None
        assert book.active.cell(2, 10).value == datetime(2026, 1, 2, 3, 4)
        book.close()
        original = db.get(CustomerUpload, first["upload_id"])
        assert original is not None
        source = db.get(Artifact, original.artifact_id)
        assert source is not None
        assert (
            hashlib.sha256(
                (setup_ledger[-1] / source.storage_key).read_bytes()
            ).hexdigest()
            == hashlib.sha256(setup_ledger[3]).hexdigest()
        )


def test_replay_conflict_metadata_and_old_selection(
    client: TestClient, setup_ledger: LedgerSetup
) -> None:
    first = read(client, setup_ledger)
    body = edit(first)
    key = str(uuid.uuid4())
    a = post(client, setup_ledger, body, key)
    b = post(client, setup_ledger, body, key)
    assert a.status_code == b.status_code == 201 and a.json() == b.json()
    assert (
        post(client, setup_ledger, {**body, "reason": "其他意图"}, key).status_code
        == 409
    )
    assert post(client, setup_ledger, body).status_code == 409
    current = read(client, setup_ledger)
    meta = edit(current, operation="manage")
    meta["fields"] = {}
    meta["management"] = {"owner": "人工确认", "tags": ["关注"]}
    r = post(client, setup_ledger, meta)
    assert r.status_code == 201, r.text
    newer = read(client, setup_ledger)
    assert (
        newer["upload_id"] == current["upload_id"]
        and newer["revision_id"] != current["revision_id"]
    )
    assert newer["data"][0]["management"]["owner"] == "人工确认"
    assert newer["data"][0]["fields"]["asset_owner"] == "原负责人"
    root, headers, *_ = setup_ledger
    assert (
        client.get(root + f"/customer-ledger/operations/{key}", headers=headers).json()[
            "id"
        ]
        == a.json()["id"]
    )
    assert (
        client.post(
            root + f"/customer-uploads/{first['upload_id']}/select", headers=headers
        ).status_code
        == 200
    )
    selected = read(client, setup_ledger)
    assert (
        selected["revision_id"] is None
        and selected["data"][0]["management"]["owner"] == ""
    )
    assert (
        read(client, setup_ledger, revision_id=r.json()["id"])["data"][0]["management"][
            "owner"
        ]
        == "人工确认"
    )


def test_concurrent_saves_have_one_winner(
    client: TestClient, setup_ledger: LedgerSetup
) -> None:
    first = read(client, setup_ledger)
    body = edit(first)
    with ThreadPoolExecutor(max_workers=2) as workers:
        statuses = list(
            workers.map(
                lambda _: post(client, setup_ledger, body).status_code, range(2)
            )
        )
    assert sorted(statuses) == [201, 409]


def test_full_upload_replacement_preview_apply_replay_and_conflict(
    client: TestClient, setup_ledger: LedgerSetup
) -> None:
    root, headers, original, _data, _path = setup_ledger
    page = read(client, setup_ledger)
    book = Workbook()
    sheet = book.active
    sheet.append(list(ledger.HEADERS))
    sheet.append(["2001:db8:10::20", 443, 443, "是", "example.net"])
    sheet.append(["2001:db8:10::30", 443, 443, "否", None])
    stream = io.BytesIO()
    book.save(stream)
    book.close()
    candidate_response = client.post(
        root + "/customer-uploads",
        headers=headers,
        files={"file": ("replacement.xlsx", stream.getvalue())},
    )
    assert candidate_response.status_code == 201, candidate_response.text
    candidate = candidate_response.json()
    body = {
        "candidate_upload_id": candidate["id"],
        "expected_upload_id": original["id"],
        "expected_revision_id": None,
        "expected_profile_id": page["current_profile_id"],
    }
    preview = client.post(
        root + "/customer-ledger/replacements/preview", headers=headers, json=body
    )
    assert preview.status_code == 200, preview.text
    assert preview.headers["Cache-Control"] == "private, no-store"
    assert read(client, setup_ledger)["upload_id"] == original["id"]
    assert preview.json() == {
        "candidate_upload_id": candidate["id"],
        "current_upload_id": original["id"],
        "current_revision_id": None,
        "profile_id": page["current_profile_id"],
        "current_record_count": 61,
        "current_unique_ips": 1,
        "candidate_record_count": 2,
        "candidate_unique_ips": 2,
        "added_ips": 1,
        "removed_ips": 0,
        "changed_ip_declarations": 1,
    }
    key = "replace-ledger-once"
    applied = client.post(
        root + "/customer-ledger/replacements",
        headers={**headers, "Idempotency-Key": key},
        json=body,
    )
    assert applied.status_code == 201, applied.text
    current = read(client, setup_ledger)
    assert current["upload_id"] == candidate["id"] and current["revision_id"] is None
    assert read(client, setup_ledger, upload_id=original["id"])["count"] == 61
    conflicting_key = client.post(
        root + "/customer-ledger/replacements",
        headers={**headers, "Idempotency-Key": key},
        json={**body, "candidate_upload_id": original["id"]},
    )
    assert conflicting_key.status_code == 409
    assert conflicting_key.json()["detail"]["code"] == "ledger_key_conflict"
    assert (
        client.post(
            root + "/customer-ledger/replacements",
            headers={**headers, "Idempotency-Key": key},
            json=body,
        ).json()
        == applied.json()
    )
    changed = post(client, setup_ledger, edit(current), "later-ledger-save")
    assert changed.status_code == 201, changed.text
    # A recovered receipt documents the original action; it never rewinds later input.
    replay = client.post(
        root + "/customer-ledger/replacements",
        headers={**headers, "Idempotency-Key": key},
        json=body,
    )
    assert replay.status_code == 201 and replay.json() == applied.json()
    assert read(client, setup_ledger)["revision_id"] == changed.json()["id"]
    assert (
        client.post(
            root + "/customer-ledger/replacements/preview", headers=headers, json=body
        ).status_code
        == 409
    )


def test_concurrent_full_replacements_have_one_winner(
    client: TestClient, setup_ledger: LedgerSetup
) -> None:
    root, headers, original, _data, _path = setup_ledger
    page = read(client, setup_ledger)
    candidates = []
    for suffix in ("31", "32"):
        book = Workbook()
        sheet = book.active
        sheet.append(list(ledger.HEADERS))
        sheet.append([f"2001:db8:10::{suffix}", 443, 443, "否", None])
        stream = io.BytesIO()
        book.save(stream)
        book.close()
        response = client.post(
            root + "/customer-uploads",
            headers=headers,
            files={"file": (f"replacement-{suffix}.xlsx", stream.getvalue())},
        )
        assert response.status_code == 201, response.text
        candidates.append(response.json()["id"])

    def replace(candidate_id: str) -> int:
        response = client.post(
            root + "/customer-ledger/replacements",
            headers={**headers, "Idempotency-Key": f"replace-{candidate_id}"},
            json={
                "candidate_upload_id": candidate_id,
                "expected_upload_id": original["id"],
                "expected_revision_id": None,
                "expected_profile_id": page["current_profile_id"],
            },
        )
        return int(response.status_code)

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(replace, candidates)) == [201, 409]


def test_replacement_recovery_permissions_and_failed_audit_are_atomic(
    client: TestClient, setup_ledger: LedgerSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, admin, original, *_ = setup_ledger
    current = read(client, setup_ledger)
    corrected = post(client, setup_ledger, edit(current)).json()
    current = read(client, setup_ledger)
    body = {
        "candidate_upload_id": original["id"],
        "expected_upload_id": current["upload_id"],
        "expected_revision_id": corrected["id"],
        "expected_profile_id": current["current_profile_id"],
    }
    url = root + "/customer-ledger/replacements"
    key = "replacement-lost-ack"
    viewer = _create_member(
        client, admin, project_id=root.split("/")[-1], roles=["viewer"]
    )
    assert (
        client.post(
            url, headers={**viewer, "Idempotency-Key": key}, json=body
        ).status_code
        == 404
    )
    assert read(client, setup_ledger)["revision_id"] == corrected["id"]
    # A receipt and current selection must roll back together on a failed audit.
    with Session(engine) as audit_db, reject_audit_inserts(audit_db):
        failed = client.post(
            url, headers={**admin, "Idempotency-Key": "audit-failure"}, json=body
        )
    assert failed.status_code == 503
    assert read(client, setup_ledger)["revision_id"] == corrected["id"]
    assert client.get(url + "/audit-failure", headers=admin).status_code == 404
    original_commit = Session.commit

    def commit_then_fail(session: Session) -> None:
        original_commit(session)
        raise SQLAlchemyError("lost acknowledgement")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", commit_then_fail)
        applied = client.post(url, headers={**admin, "Idempotency-Key": key}, json=body)
    assert applied.status_code == 201, applied.text
    recovered = client.get(url + "/" + key, headers=admin)
    assert recovered.status_code == 200 and recovered.json() == applied.json()
    assert recovered.headers["Cache-Control"] == "private, no-store"
    assert recovered.json()["project_id"] == root.split("/")[-1]
    assert client.get(url + "/" + key, headers=viewer).status_code == 404
    with Session(engine) as session:
        rows = session.exec(
            select(CustomerUploadReplacement).where(
                CustomerUploadReplacement.project_id == uuid.UUID(root.split("/")[-1])
            )
        ).all()
        assert len(rows) == 1 and rows[0].sealed
        with pytest.raises(SQLAlchemyError, match="immutable"):
            session.execute(
                text("DELETE FROM customer_upload_replacements WHERE id=:id"),
                {"id": rows[0].id},
            )
            session.commit()
        session.rollback()


def test_archive_add_validation_and_immutability(
    client: TestClient, setup_ledger: LedgerSetup
) -> None:
    first = read(client, setup_ledger)
    body = edit(first, operation="archive")
    body["fields"] = {}
    r = post(client, setup_ledger, body)
    assert r.status_code == 201, r.text
    current = read(client, setup_ledger)
    assert current["count"] == 60
    archived = read(client, setup_ledger, archived=True)
    assert archived["count"] == 1
    body = edit(current, operation="add", fields=first["data"][0]["fields"])
    body["entry_id"] = None
    added = post(client, setup_ledger, body)
    assert added.status_code == 201, added.text
    current = read(client, setup_ledger)
    assert current["count"] == 61
    interval = post(
        client, setup_ledger, edit(current, fields={"start_port": 10_001, "end_port": 10_002})
    )
    assert interval.status_code == 201, interval.text
    current = read(client, setup_ledger)
    assert current["data"][0]["fields"]["start_port"] == 10_001
    assert current["data"][0]["fields"]["end_port"] == 10_002
    derived = read(client, setup_ledger, original=False)
    assert derived["data"][0]["fields"]["start_port"] == 10_001
    assert derived["data"][0]["fields"]["end_port"] == 10_002
    with Session(engine) as db:
        derived_upload = db.get(CustomerUpload, current["upload_id"])
        assert derived_upload is not None
        derived_artifact = db.get(Artifact, derived_upload.artifact_id)
        assert derived_artifact is not None
        book = load_workbook(
            setup_ledger[-1] / derived_artifact.storage_key, read_only=True
        )
        sheet = book.active
        assert sheet is not None
        assert any(
            row[1] == 10_001 and row[2] == 10_002
            for row in sheet.iter_rows(min_row=2, values_only=True)
        )
        book.close()
    invalid_ip = post(
        client, setup_ledger, edit(current, fields={"asset_ip": "fe80::1%en0"})
    )
    assert invalid_ip.status_code == 422
    assert invalid_ip.json()["detail"] == {
        "code": "ledger_fields_invalid",
        "field": "asset_ip",
        "row": current["data"][0]["position"],
        "reason": "invalid_ip",
        "location": "ledger",
    }
    with Session(engine) as db:
        with pytest.raises(SQLAlchemyError, match="immutable"):
            db.execute(
                text(
                    "UPDATE customer_ledger_revisions SET reason=:reason WHERE id=:id"
                ),
                {"reason": "changed", "id": added.json()["id"]},
            )
            db.commit()
        db.rollback()
        with pytest.raises(SQLAlchemyError, match="immutable"):
            db.execute(
                text(
                    "DELETE FROM customer_ledger_entry_versions WHERE revision_id=:id"
                ),
                {"id": added.json()["id"]},
            )
            db.commit()
        db.rollback()


@pytest.mark.parametrize(
    ("worksheet_row", "expected_row"),
    [(2, 2), (99, None)],
)
def test_acceptance_diagnostic_maps_generated_rows_to_ledger(
    client: TestClient,
    setup_ledger: LedgerSetup,
    monkeypatch: pytest.MonkeyPatch,
    worksheet_row: int,
    expected_row: int | None,
) -> None:
    first = read(client, setup_ledger)
    archive = edit(first, operation="archive")
    archive["fields"] = {}
    archived = post(client, setup_ledger, archive)
    assert archived.status_code == 201, archived.text
    current = read(client, setup_ledger)
    assert current["data"][0]["position"] == 2

    def reject(**_kwargs: Any) -> NoReturn:
        raise customer_uploads.CustomerUploadAcceptanceError(
            "invalid_required_value",
            diagnostic=Diagnostic(
                code="invalid_required_value",
                field="start_port",
                row=worksheet_row,
                column=4,
                reason="port_out_of_range",
                location="worksheet",
                limit=65_535,
                observed=70_000,
                measurement="exact",
                unit="port_number",
            ),
        )

    monkeypatch.setattr(customer_uploads, "accept_customer_upload", reject)
    response = post(
        client,
        setup_ledger,
        edit(current, fields={"start_port": 10_001, "end_port": 10_002}),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "column" not in detail
    expected: dict[str, object] = {
        "code": "invalid_required_value",
        "field": "start_port",
        "reason": "port_out_of_range",
        "location": "ledger",
        "limit": 65_535,
        "observed": 70_000,
        "measurement": "exact",
        "unit": "port_number",
    }
    if expected_row is not None:
        expected["row"] = expected_row
    assert detail == expected


def test_permissions_recovery_scope_and_archive(
    client: TestClient, setup_ledger: LedgerSetup
) -> None:
    root, admin, *_ = setup_ledger
    project_id = root.split("/")[-1]
    first = read(client, setup_ledger)
    op = post(client, setup_ledger, edit(first), "scope-key")
    assert op.status_code == 201
    for roles in [["viewer"], ["approver"]]:
        headers = _create_member(client, admin, project_id=project_id, roles=roles)
        assert (
            client.get(root + "/customer-ledger", headers=headers).json()["can_edit"]
            is False
        )
        assert (
            client.post(
                root + "/customer-ledger/revisions",
                headers={**headers, "Idempotency-Key": "denied"},
                json=edit(first),
            ).status_code
            == 404
        )
        assert (
            client.get(
                root + "/customer-ledger/operations/scope-key", headers=headers
            ).status_code
            == 404
        )
    other = _create_project(client, admin)
    assert (
        client.get(
            f"{settings.API_V1_STR}/projects/{other['id']}/customer-ledger",
            headers=admin,
            params={"revision_id": op.json()["id"]},
        ).status_code
        == 404
    )
    assert client.post(root + "/archive", headers=admin).status_code == 200
    assert (
        post(client, setup_ledger, edit(read(client, setup_ledger))).status_code == 409
    )


@pytest.mark.parametrize("failure", ["audit", "commit", "writer"])
def test_failure_keeps_input_and_cleans_only_new_artifacts(
    client: TestClient,
    db: Session,
    setup_ledger: LedgerSetup,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    first = read(client, setup_ledger)
    files = set(setup_ledger[-1].rglob("*.xlsx"))

    def fail(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise SQLAlchemyError("injected")

    if failure == "audit":
        # Prior tests may leave a read transaction on the shared fixture.
        # Reuse it so the fault-injection helper releases that lock before DDL.
        db.exec(select(AuditEvent.action)).first()
        with reject_audit_inserts(db):
            result = post(client, setup_ledger, edit(first))
    else:
        with monkeypatch.context() as patch:
            patch.setattr(
                Session, "commit", fail
            ) if failure == "commit" else patch.setattr(ledger, "_write_workbook", fail)
            result = post(client, setup_ledger, edit(first))
    assert result.status_code == 500, result.text
    assert read(client, setup_ledger)["upload_id"] == first["upload_id"]
    assert set(setup_ledger[-1].rglob("*.xlsx")) == files
    with Session(engine) as db:
        assert not db.exec(
            select(CustomerLedgerRevision).where(
                CustomerLedgerRevision.project_id == uuid.UUID(first["project_id"])
            )
        ).all()


@pytest.mark.parametrize("setup_ledger", [1], indirect=True)
def test_last_entry_and_invalid_management_rejected(
    client: TestClient, setup_ledger: LedgerSetup
) -> None:
    first = read(client, setup_ledger)
    body = edit(first, operation="archive")
    body["fields"] = {}
    response = post(client, setup_ledger, body)
    assert (
        response.status_code == 422
        and response.json()["detail"]["code"] == "ledger_last_entry"
    )
    assert read(client, setup_ledger)["upload_id"] == first["upload_id"]
    body = edit(first, operation="manage")
    body["fields"] = {}
    body["management"] = {"tags": ["x" * 65]}
    assert post(client, setup_ledger, body).status_code == 422


def test_lost_commit_acknowledgement_recovers_committed_artifact(
    client: TestClient, setup_ledger: LedgerSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = read(client, setup_ledger)
    key = "lost-commit"
    original_commit = Session.commit

    def commit_then_fail(session: Session) -> None:
        original_commit(session)
        raise SQLAlchemyError("lost acknowledgement")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", commit_then_fail)
        response = post(client, setup_ledger, edit(first), key)
    assert response.status_code == 201, response.text
    current = read(client, setup_ledger)
    assert current["revision_id"] == response.json()["id"]
    with Session(engine) as session:
        upload = session.get(CustomerUpload, current["upload_id"])
        assert upload is not None
        artifact = session.get(Artifact, upload.artifact_id)
        assert artifact is not None
        assert (setup_ledger[-1] / artifact.storage_key).is_file()


@pytest.mark.parametrize("dimension", ["A1:K2", "A1:XFD1048576"])
def test_declared_dimensions_cannot_truncate_or_expand_ledger(
    client: TestClient, setup_ledger: LedgerSetup, dimension: str
) -> None:
    root, headers, _upload, raw, _files = setup_ledger
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(raw)) as original,
        zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as replacement,
    ):
        for info in original.infolist():
            content = original.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                content = re.sub(
                    rb'<dimension ref="[^"]+"',
                    f'<dimension ref="{dimension}"'.encode(),
                    content,
                )
            replacement.writestr(info, content)
    accepted = client.post(
        root + "/customer-uploads",
        headers=headers,
        files={"file": ("declared-dimension.xlsx", output.getvalue())},
    )
    assert accepted.status_code == 201, accepted.text
    upload_id = accepted.json()["id"]
    assert (
        client.post(
            root + f"/customer-uploads/{upload_id}/select", headers=headers
        ).status_code
        == 200
    )
    before = read(client, setup_ledger)
    assert before["count"] == 61
    result = post(client, setup_ledger, edit(before))
    assert result.status_code == 201, result.text
    assert read(client, setup_ledger)["count"] == 61


@pytest.mark.parametrize(
    "fields",
    [
        {"asset_owner": "bad\u0001owner"},
        {"department": {"kind": "datetime", "value": "2026-09-15T12:00:00+08:00"}},
    ],
)
def test_unsupported_cell_values_are_stable_validation_failures(
    client: TestClient, setup_ledger: LedgerSetup, fields: dict[str, Any]
) -> None:
    first = read(client, setup_ledger)
    response = post(client, setup_ledger, edit(first, fields=fields))
    assert (
        response.status_code == 422
        and response.json()["detail"]["code"] == "ledger_fields_invalid"
    )
    assert read(client, setup_ledger)["upload_id"] == first["upload_id"]


def test_unchanged_input_does_not_materialize_another_workbook(
    client: TestClient, setup_ledger: LedgerSetup
) -> None:
    first = read(client, setup_ledger)
    result = post(client, setup_ledger, edit(first, fields=first["data"][0]["fields"]))
    assert result.status_code == 201, result.text
    assert result.json()["input_changed"] is False
    assert result.json()["upload_id"] == first["upload_id"]


@pytest.mark.parametrize("bad", ["null\x00text", "bad\ud800text"])
def test_invalid_database_text_is_rejected_before_an_intent(
    client: TestClient, setup_ledger: LedgerSetup, bad: str
) -> None:
    first = read(client, setup_ledger)
    body = edit(first, operation="manage")
    body["fields"] = {}
    body["management"] = {"owner": bad}
    root, headers, *_ = setup_ledger
    import json

    result = client.post(
        root + "/customer-ledger/revisions",
        headers={
            **headers,
            "Idempotency-Key": "bad-text",
            "Content-Type": "application/json",
        },
        content=json.dumps(body, ensure_ascii=True),
    )
    assert result.status_code == 422
    assert read(client, setup_ledger)["revision_id"] == first["revision_id"]


def test_replacement_cannot_reset_current_manual_revision(
    client: TestClient, setup_ledger: LedgerSetup
) -> None:
    first = read(client, setup_ledger)
    managed = edit(first, operation="manage", management={"tags": ["retain-me"]})
    managed["fields"] = {}
    changed = post(client, setup_ledger, managed)
    assert changed.status_code == 201, changed.text
    current = read(client, setup_ledger)
    root, headers, *_ = setup_ledger
    body = {
        "candidate_upload_id": current["current_upload_id"],
        "expected_upload_id": current["current_upload_id"],
        "expected_revision_id": current["current_revision_id"],
        "expected_profile_id": current["current_profile_id"],
    }
    for suffix in [
        "/customer-ledger/replacements/preview",
        "/customer-ledger/replacements",
    ]:
        rejected = client.post(
            root + suffix,
            headers=headers | {"Idempotency-Key": "same-current-upload"},
            json=body,
        )
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["detail"]["code"] == "ledger_replacement_same_upload"
    after = read(client, setup_ledger)
    assert after["current_revision_id"] == current["current_revision_id"]
    assert after["data"] == current["data"]


def test_first_selection_preview_apply_replay_and_conflict_without_current_input(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    root = f"{settings.API_V1_STR}/projects/{project['id']}"
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(list(ledger.HEADERS))
    sheet.append(["2001:db8:10::40", 443, 443, "是", "example.net"])
    sheet.append(["2001:db8:10::41", 443, 443, "否", None])
    stream = io.BytesIO()
    book.save(stream)
    book.close()
    candidate_response = client.post(
        root + "/customer-uploads",
        headers=superuser_token_headers,
        files={"file": ("first-selection.xlsx", stream.getvalue())},
    )
    assert candidate_response.status_code == 201, candidate_response.text
    candidate = candidate_response.json()
    listings = client.get(root + "/customer-uploads", headers=superuser_token_headers)
    assert listings.status_code == 200, listings.text
    assert listings.json()["current_customer_upload_id"] is None
    page = client.get(root + "/customer-ledger", headers=superuser_token_headers)
    assert page.status_code == 200, page.text
    initial = page.json()
    assert (
        initial["upload_id"] is None
        and initial["current_upload_id"] is None
        and initial["current_revision_id"] is None
        and initial["can_edit"] is False
        and initial["data"] == []
    )
    body = {
        "candidate_upload_id": candidate["id"],
        "expected_upload_id": None,
        "expected_revision_id": None,
        "expected_profile_id": initial["current_profile_id"],
    }
    preview = client.post(
        root + "/customer-ledger/replacements/preview",
        headers=superuser_token_headers,
        json=body,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json() == {
        "candidate_upload_id": candidate["id"],
        "current_upload_id": None,
        "current_revision_id": None,
        "profile_id": initial["current_profile_id"],
        "current_record_count": 0,
        "current_unique_ips": 0,
        "candidate_record_count": 2,
        "candidate_unique_ips": 2,
        "added_ips": 2,
        "removed_ips": 0,
        "changed_ip_declarations": 0,
    }
    key = "first-selection-once"
    applied = client.post(
        root + "/customer-ledger/replacements",
        headers={**superuser_token_headers, "Idempotency-Key": key},
        json=body,
    )
    assert applied.status_code == 201, applied.text
    assert applied.json()["expected_upload_id"] is None
    replay = client.post(
        root + "/customer-ledger/replacements",
        headers={**superuser_token_headers, "Idempotency-Key": key},
        json=body,
    )
    assert replay.status_code == 201 and replay.json() == applied.json()
    after = client.get(root + "/customer-ledger", headers=superuser_token_headers)
    assert after.status_code == 200, after.text
    selected = after.json()
    assert (
        selected["upload_id"] == candidate["id"]
        and selected["current_upload_id"] == candidate["id"]
        and selected["can_edit"] is True
        and selected["count"] == 2
    )
    stale = client.post(
        root + "/customer-ledger/replacements/preview",
        headers=superuser_token_headers,
        json=body,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "ledger_version_conflict"
    second_book = Workbook()
    second_sheet = second_book.active
    assert second_sheet is not None
    second_sheet.append(list(ledger.HEADERS))
    second_sheet.append(["2001:db8:10::42", 443, 443, "是", "example.net"])
    second_stream = io.BytesIO()
    second_book.save(second_stream)
    second_book.close()
    second_response = client.post(
        root + "/customer-uploads",
        headers=superuser_token_headers,
        files={"file": ("another-candidate.xlsx", second_stream.getvalue())},
    )
    assert second_response.status_code == 201, second_response.text
    conflicting = client.post(
        root + "/customer-ledger/replacements",
        headers={**superuser_token_headers, "Idempotency-Key": key},
        json={**body, "candidate_upload_id": second_response.json()["id"]},
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["detail"]["code"] == "ledger_key_conflict"


def _xlsx(rows: list[list[Any]], headers: list[str] | None = None) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(list(headers or ledger.HEADERS))
    for row in rows:
        sheet.append(row)
    stream = io.BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


def _upload(
    client: TestClient,
    root: str,
    headers: dict[str, str],
    rows: list[list[Any]],
    *,
    name: str = "candidate.xlsx",
    header_names: list[str] | None = None,
) -> dict[str, Any]:
    response = client.post(
        root + "/customer-uploads",
        headers=headers,
        files={"file": (name, _xlsx(rows, header_names))},
    )
    assert response.status_code in {200, 201}, response.text
    return cast(dict[str, Any], response.json())


def _basis(page: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    return {
        "candidate_upload_id": candidate_id,
        "expected_upload_id": page["current_upload_id"],
        "expected_revision_id": page["current_revision_id"],
        "expected_profile_id": page["current_profile_id"],
    }


def _details(
    client: TestClient,
    root: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> Any:
    return client.post(
        root + "/customer-ledger/replacements/details", headers=headers, json=body
    )


def _first_selection(
    client: TestClient,
    root: str,
    headers: dict[str, str],
    upload: dict[str, Any],
    profile_id: str,
    key: str,
) -> Any:
    response = client.post(
        root + "/customer-ledger/replacements",
        headers={**headers, "Idempotency-Key": key},
        json={
            "candidate_upload_id": upload["id"],
            "expected_upload_id": None,
            "expected_revision_id": None,
            "expected_profile_id": profile_id,
        },
    )
    assert response.status_code == 201, response.text
    return response


def _new_project(
    client: TestClient, headers: dict[str, str]
) -> tuple[str, dict[str, Any]]:
    project = _create_project(client, headers)
    root = f"{settings.API_V1_STR}/projects/{project['id']}"
    page = client.get(root + "/customer-ledger", headers=headers)
    assert page.status_code == 200, page.text
    return root, page.json()


def test_replacement_details_groups_records_paging_and_offsets(
    client: TestClient, setup_ledger: LedgerSetup
) -> None:
    root, headers, original, _data, _path = setup_ledger
    page = read(client, setup_ledger)
    rows = [
        [f"2001:db8:20::{n:x}", 443, 443, "否", None] for n in range(1, 27)
    ] + [["2001:db8:30::1", 443, 443, "否", None] for _ in range(12)]
    candidate = _upload(client, root, headers, rows, name="groups.xlsx")
    basis = _basis(page, candidate["id"])
    preview = client.post(
        root + "/customer-ledger/replacements/preview", headers=headers, json=basis
    )
    assert preview.status_code == 200, preview.text
    assert preview.json() == {
        "candidate_upload_id": candidate["id"],
        "current_upload_id": original["id"],
        "current_revision_id": None,
        "profile_id": page["current_profile_id"],
        "current_record_count": 61,
        "current_unique_ips": 1,
        "candidate_record_count": 38,
        "candidate_unique_ips": 27,
        "added_ips": 27,
        "removed_ips": 1,
        "changed_ip_declarations": 0,
    }
    me = client.get(settings.API_V1_STR + "/users/me", headers=headers)
    assert me.status_code == 200
    actor_id = me.json()["id"]
    project_id = root.split("/")[-1]

    def groups(skip: int, limit: int = 25) -> dict[str, Any]:
        body = {
            "basis": basis,
            "selector": {
                "kind": "groups",
                "category": "added",
                "skip": skip,
                "limit": limit,
            },
        }
        response = _details(client, root, headers, body)
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "private, no-store"
        value = response.json()
        assert value["actor_id"] == actor_id
        assert value["project_id"] == project_id
        assert value["basis"] == basis
        assert value["selector"] == body["selector"]
        assert value["kind"] == "groups"
        assert value["category"] == "added"
        assert value["skip"] == skip
        assert value["limit"] == limit
        assert value["total_groups"] == 27
        assert len(value["groups"]) == min(limit, max(0, 27 - skip))
        return cast(dict[str, Any], value)

    first, second = groups(0), groups(25)
    assert len(first["groups"]) == 25 and len(second["groups"]) == 2
    listed = first["groups"] + second["groups"]
    assert len({group["canonical_ip"] for group in listed}) == 27
    assert [group["canonical_ip"] for group in listed] == sorted(
        (group["canonical_ip"] for group in listed),
        key=lambda value: (
            ipaddress.ip_address(value).version,
            int(ipaddress.ip_address(value)),
        ),
    )
    duplicate = next(
        group for group in listed if group["canonical_ip"] == "2001:db8:30::1"
    )
    assert duplicate == {
        "canonical_ip": "2001:db8:30::1",
        "current_records": 0,
        "candidate_records": 12,
    }
    assert all(group["current_records"] == 0 for group in listed)
    beyond = groups(100)
    assert beyond["groups"] == [] and beyond["total_groups"] == 27
    assert groups(0, 25)["groups"][0]["canonical_ip"] == "2001:db8:20::1"

    removed = _details(
        client,
        root,
        headers,
        {
            "basis": basis,
            "selector": {"kind": "groups", "category": "removed"},
        },
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["total_groups"] == 1
    assert removed.json()["groups"] == [
        {
            "canonical_ip": "2001:db8:10::20",
            "current_records": 61,
            "candidate_records": 0,
        }
    ]
    assert removed.json()["limit"] == 25

    def records(side: str, skip: int, limit: int = 10) -> dict[str, Any]:
        body = {
            "basis": basis,
            "selector": {
                "kind": "records",
                "category": "added",
                "canonical_ip": "2001:db8:30::1",
                "side": side,
                "skip": skip,
                "limit": limit,
            },
        }
        expected_total = 12 if side == "candidate" else 0
        response = _details(client, root, headers, body)
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "private, no-store"
        value = response.json()
        assert value["actor_id"] == actor_id and value["project_id"] == project_id
        assert value["basis"] == basis
        assert value["kind"] == "records"
        assert value["category"] == "added"
        assert value["canonical_ip"] == "2001:db8:30::1"
        assert value["side"] == side
        assert value["selector"] == body["selector"]
        assert value["total_records"] == expected_total
        assert len(value["records"]) == min(limit, max(0, expected_total - skip))
        for record in value["records"]:
            assert record["canonical_ip"] == "2001:db8:30::1"
            assert record["fields"]
        return cast(dict[str, Any], value)

    current_records_page = records("current", 0)
    assert current_records_page["total_records"] == 0
    assert current_records_page["records"] == []
    first_records, second_records = records("candidate", 0), records("candidate", 10)
    assert len(first_records["records"]) == 10
    assert len(second_records["records"]) == 2
    every = first_records["records"] + second_records["records"]
    assert len({record["entry_id"] for record in every}) == 12
    assert [record["position"] for record in every] == sorted(
        record["position"] for record in every
    )
    assert all(record["fields"]["serial"] is None for record in every)
    empty = records("candidate", 100)
    assert empty["records"] == [] and empty["total_records"] == 12


def test_replacement_details_multiplicity_counts_and_change_sets(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    root, initial = _new_project(client, superuser_token_headers)
    a = ["192.0.2.10", 443, 443, "否", None]
    base = _upload(
        client, root, superuser_token_headers, [a, a], name="base-duplicates.xlsx"
    )
    _first_selection(
        client,
        root,
        superuser_token_headers,
        base,
        initial["current_profile_id"],
        "duplicate-base",
    )
    page = client.get(root + "/customer-ledger", headers=superuser_token_headers)
    assert page.status_code == 200, page.text
    page = page.json()
    assert page["count"] == 2 and page["unique_ips"] == 1
    basis = _basis(page, "")

    def preview(candidate_id: str) -> dict[str, Any]:
        body = {**basis, "candidate_upload_id": candidate_id}
        response = client.post(
            root + "/customer-ledger/replacements/preview",
            headers=superuser_token_headers,
            json=body,
        )
        assert response.status_code == 200, response.text
        return cast(dict[str, Any], response.json())

    def detail(candidate_id: str, selector: dict[str, Any]) -> Any:
        body = {
            "basis": {**basis, "candidate_upload_id": candidate_id},
            "selector": selector,
        }
        return _details(client, root, superuser_token_headers, body)

    one = _upload(client, root, superuser_token_headers, [a], name="one.xlsx")
    impact = preview(one["id"])
    assert (
        impact["current_record_count"],
        impact["current_unique_ips"],
        impact["candidate_record_count"],
        impact["candidate_unique_ips"],
        impact["added_ips"],
        impact["removed_ips"],
        impact["changed_ip_declarations"],
    ) == (2, 1, 1, 1, 0, 0, 1)
    group = detail(one["id"], {"kind": "groups", "category": "changed"})
    assert group.status_code == 200, group.text
    assert group.json()["total_groups"] == 1
    assert group.json()["groups"] == [
        {
            "canonical_ip": "192.0.2.10",
            "current_records": 2,
            "candidate_records": 1,
        }
    ]
    current_side = detail(
        one["id"],
        {
            "kind": "records",
            "category": "changed",
            "canonical_ip": "192.0.2.10",
            "side": "current",
        },
    )
    candidate_side = detail(
        one["id"],
        {
            "kind": "records",
            "category": "changed",
            "canonical_ip": "192.0.2.10",
            "side": "candidate",
        },
    )
    assert current_side.status_code == candidate_side.status_code == 200
    assert current_side.json()["total_records"] == 2
    assert candidate_side.json()["total_records"] == 1
    current_rows = current_side.json()["records"]
    candidate_rows = candidate_side.json()["records"]
    assert len({row["entry_id"] for row in current_rows}) == 2
    assert current_rows[0]["fields"] == current_rows[1]["fields"]
    assert current_rows[0]["entry_id"] != current_rows[1]["entry_id"]
    assert current_rows[0]["entry_id"] != candidate_rows[0]["entry_id"]
    assert [row["position"] for row in current_rows] == [1, 2]

    mixed = _upload(
        client,
        root,
        superuser_token_headers,
        [a, ["192.0.2.10", 8443, 8443, "否", None]],
        name="mixed-duplicates.xlsx",
    )
    impact = preview(mixed["id"])
    assert (
        impact["current_record_count"],
        impact["current_unique_ips"],
        impact["candidate_record_count"],
        impact["candidate_unique_ips"],
        impact["added_ips"],
        impact["removed_ips"],
        impact["changed_ip_declarations"],
    ) == (2, 1, 2, 1, 0, 0, 1)
    group = detail(mixed["id"], {"kind": "groups", "category": "changed"})
    assert group.status_code == 200, group.text
    assert group.json()["groups"] == [
        {
            "canonical_ip": "192.0.2.10",
            "current_records": 2,
            "candidate_records": 2,
        }
    ]
    mixed_candidate_rows = detail(
        mixed["id"],
        {
            "kind": "records",
            "category": "changed",
            "canonical_ip": "192.0.2.10",
            "side": "candidate",
        },
    ).json()["records"]
    assert [row["fields"]["start_port"] for row in mixed_candidate_rows] == [
        {"kind": "number", "numeric_type": "integer", "value": "443"},
        {"kind": "number", "numeric_type": "integer", "value": "8443"},
    ]

    distinct = _upload(
        client,
        root,
        superuser_token_headers,
        [["192.0.2.10", 443, 443, "否", None, None, None, None, None, None, 1],
         ["192.0.2.10", 443, 443, "否", None, None, None, None, None, None, 2]],
        name="distinct-duplicates.xlsx",
    )
    impact = preview(distinct["id"])
    assert (
        impact["current_record_count"],
        impact["candidate_record_count"],
        impact["candidate_unique_ips"],
        impact["added_ips"],
        impact["removed_ips"],
        impact["changed_ip_declarations"],
    ) == (2, 2, 1, 0, 0, 1)
    group = detail(distinct["id"], {"kind": "groups", "category": "changed"})
    assert group.json()["groups"][0]["current_records"] == 2
    assert group.json()["groups"][0]["candidate_records"] == 2
    candidate_rows = detail(
        distinct["id"],
        {
            "kind": "records",
            "category": "changed",
            "canonical_ip": "192.0.2.10",
            "side": "candidate",
        },
    ).json()["records"]
    assert [row["fields"]["serial"] for row in candidate_rows] == [
        {"kind": "number", "numeric_type": "integer", "value": "1"},
        {"kind": "number", "numeric_type": "integer", "value": "2"},
    ]

    identical = _upload(
        client,
        root,
        superuser_token_headers,
        [[*row, *([None] * (len(ledger.HEADERS) - len(row))), "ignored"] for row in [a, a]],
        name="identical.xlsx",
        header_names=[*ledger.HEADERS, "备注"],
    )
    impact = preview(identical["id"])
    assert impact["added_ips"] == 0
    assert impact["removed_ips"] == 0
    assert impact["changed_ip_declarations"] == 0
    for category in ("added", "removed", "changed"):
        response = detail(identical["id"], {"kind": "groups", "category": category})
        assert response.status_code == 200, response.text
        assert response.json()["total_groups"] == 0
        assert response.json()["groups"] == []
    missing = detail(
        identical["id"],
        {
            "kind": "records",
            "category": "changed",
            "canonical_ip": "192.0.2.10",
            "side": "current",
        },
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "ledger_diff_group_not_found"
    assert missing.headers["Cache-Control"] == "private, no-store"


def test_replacement_details_first_selection_counts_are_ip_and_record_honest(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    root, initial = _new_project(client, superuser_token_headers)
    rows = [
        ["192.0.2.60", 443, 443, "否", None],
        ["192.0.2.60", 8443, 8443, "否", None],
        ["192.0.2.61", 443, 443, "否", None],
    ]
    candidate = _upload(client, root, superuser_token_headers, rows, name="first.xlsx")
    basis = {
        "candidate_upload_id": candidate["id"],
        "expected_upload_id": None,
        "expected_revision_id": None,
        "expected_profile_id": initial["current_profile_id"],
    }
    preview = client.post(
        root + "/customer-ledger/replacements/preview",
        headers=superuser_token_headers,
        json=basis,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json() == {
        "candidate_upload_id": candidate["id"],
        "current_upload_id": None,
        "current_revision_id": None,
        "profile_id": initial["current_profile_id"],
        "current_record_count": 0,
        "current_unique_ips": 0,
        "candidate_record_count": 3,
        "candidate_unique_ips": 2,
        "added_ips": 2,
        "removed_ips": 0,
        "changed_ip_declarations": 0,
    }
    added = _details(
        client,
        root,
        superuser_token_headers,
        {"basis": basis, "selector": {"kind": "groups", "category": "added"}},
    )
    assert added.status_code == 200, added.text
    assert added.json()["total_groups"] == 2
    assert added.json()["groups"] == [
        {"canonical_ip": "192.0.2.60", "current_records": 0, "candidate_records": 2},
        {"canonical_ip": "192.0.2.61", "current_records": 0, "candidate_records": 1},
    ]
    for category in ("removed", "changed"):
        empty = _details(
            client,
            root,
            superuser_token_headers,
            {"basis": basis, "selector": {"kind": "groups", "category": category}},
        )
        assert empty.status_code == 200, empty.text
        assert empty.json()["total_groups"] == 0
    current_side = _details(
        client,
        root,
        superuser_token_headers,
        {
            "basis": basis,
            "selector": {
                "kind": "records",
                "category": "added",
                "canonical_ip": "192.0.2.60",
                "side": "current",
            },
        },
    )
    candidate_side = _details(
        client,
        root,
        superuser_token_headers,
        {
            "basis": basis,
            "selector": {
                "kind": "records",
                "category": "added",
                "canonical_ip": "192.0.2.60",
                "side": "candidate",
            },
        },
    )
    assert current_side.status_code == candidate_side.status_code == 200
    assert current_side.json()["total_records"] == 0
    assert current_side.json()["records"] == []
    assert candidate_side.json()["total_records"] == 2
    assert len(candidate_side.json()["records"]) == 2


def test_replacement_details_preserve_exact_typed_cell_values(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    root, initial = _new_project(client, superuser_token_headers)
    address = "192.0.2.50"
    base = _upload(
        client,
        root,
        superuser_token_headers,
        [[address, 443, 443, "否", None, "web", "owner", "dept", "port", "dep", 1]],
        name="typed-base.xlsx",
    )
    _first_selection(
        client,
        root,
        superuser_token_headers,
        base,
        initial["current_profile_id"],
        "typed-base",
    )
    page = client.get(root + "/customer-ledger", headers=superuser_token_headers)
    assert page.status_code == 200, page.text
    page = page.json()
    updated = client.post(
        root + "/customer-ledger/revisions",
        headers={**superuser_token_headers, "Idempotency-Key": "typed-update"},
        json={
            "expected_upload_id": page["upload_id"],
            "expected_revision_id": page["revision_id"],
            "expected_profile_id": page["current_profile_id"],
            "operation": "update",
            "entry_id": page["data"][0]["entry_id"],
            "fields": {
                "service_type": "",
                "asset_owner": "1",
                "port_owner": 1,
                "department": True,
                "serial": {"kind": "date", "value": "2026-01-02"},
                "web_url": None,
            },
            "reason": "exact typed values",
        },
    )
    assert updated.status_code == 201, updated.text
    page = client.get(root + "/customer-ledger", headers=superuser_token_headers)
    assert page.status_code == 200, page.text
    page = page.json()
    current_fields = page["data"][0]["fields"]
    assert current_fields["service_type"] == ""
    assert type(current_fields["asset_owner"]) is str
    assert current_fields["asset_owner"] == "1"
    assert type(current_fields["port_owner"]) is int
    assert current_fields["port_owner"] == 1
    assert current_fields["department"] is True
    assert current_fields["serial"] == {"kind": "date", "value": "2026-01-02"}
    assert current_fields["web_url"] is None

    header_names = [header for header in ledger.HEADERS if header != "部门"]
    candidate = _upload(
        client,
        root,
        superuser_token_headers,
        [
            [
                address,
                443,
                443,
                "否",
                None,
                "1",
                1,
                True,
                datetime(2026, 1, 3, 4, 5),
                None,
            ]
        ],
        name="typed-candidate.xlsx",
        header_names=header_names,
    )
    basis = _basis(page, candidate["id"])
    preview = client.post(
        root + "/customer-ledger/replacements/preview",
        headers=superuser_token_headers,
        json=basis,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["changed_ip_declarations"] == 1
    current_side = _details(
        client,
        root,
        superuser_token_headers,
        {
            "basis": basis,
            "selector": {
                "kind": "records",
                "category": "changed",
                "canonical_ip": address,
                "side": "current",
            },
        },
    )
    candidate_side = _details(
        client,
        root,
        superuser_token_headers,
        {
            "basis": basis,
            "selector": {
                "kind": "records",
                "category": "changed",
                "canonical_ip": address,
                "side": "candidate",
            },
        },
    )
    assert current_side.status_code == candidate_side.status_code == 200
    current_record = current_side.json()["records"][0]
    candidate_record = candidate_side.json()["records"][0]
    assert current_record["canonical_ip"] == address
    assert candidate_record["canonical_ip"] == address
    assert current_record["fields"]["service_type"] == ""
    assert type(current_record["fields"]["service_type"]) is str
    assert type(current_record["fields"]["asset_owner"]) is str
    assert current_record["fields"]["asset_owner"] == "1"
    assert current_record["fields"]["port_owner"] == {
        "kind": "number",
        "numeric_type": "integer",
        "value": "1",
    }
    assert current_record["fields"]["department"] is True
    assert current_record["fields"]["serial"] == {
        "kind": "date",
        "value": "2026-01-02",
    }
    assert current_record["fields"]["web_url"] is None
    assert set(current_record["fields"]) == set(ledger.FIELD_NAMES)
    assert candidate_record["fields"]["asset_owner"] == {
        "kind": "number",
        "numeric_type": "integer",
        "value": "1",
    }
    assert candidate_record["fields"]["service_type"] == "1"
    assert type(candidate_record["fields"]["service_type"]) is str
    assert candidate_record["fields"]["asset_department"] is True
    assert candidate_record["fields"]["port_owner"] == {
        "kind": "datetime",
        "value": "2026-01-03T04:05:00",
    }
    assert candidate_record["fields"]["serial"] is None
    assert "department" not in candidate_record["fields"]
    assert set(candidate_record["fields"]) == set(ledger.FIELD_NAMES) - {"department"}


def test_replacement_details_tagged_numbers_survive_transport_losslessly(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    root, initial = _new_project(client, superuser_token_headers)
    address = "192.0.2.55"
    base = _upload(
        client,
        root,
        superuser_token_headers,
        [[address, 443, 443, "否", None, None, None, None, None, None, 1]],
        name="lossless-base.xlsx",
    )
    _first_selection(
        client,
        root,
        superuser_token_headers,
        base,
        initial["current_profile_id"],
        "lossless-base",
    )
    page = client.get(root + "/customer-ledger", headers=superuser_token_headers)
    assert page.status_code == 200, page.text
    page = page.json()
    updated = client.post(
        root + "/customer-ledger/revisions",
        headers={**superuser_token_headers, "Idempotency-Key": "lossless-update"},
        json={
            "expected_upload_id": page["upload_id"],
            "expected_revision_id": page["revision_id"],
            "expected_profile_id": page["current_profile_id"],
            "operation": "update",
            "entry_id": page["data"][0]["entry_id"],
            "fields": {
                "serial": 9007199254740993,
                "start_port": 443,
                "asset_owner": -9007199254740993,
                "port_owner": 1.5,
                "department": True,
                "asset_department": {"kind": "date", "value": "2026-03-04"},
            },
            "reason": "lossless numbers",
        },
    )
    assert updated.status_code == 201, updated.text
    page = client.get(root + "/customer-ledger", headers=superuser_token_headers)
    assert page.status_code == 200, page.text
    page = page.json()
    old_cells = page["data"][0]["fields"]
    # The existing ledger API keeps its original Cell wire representation.
    assert old_cells["serial"] == 9007199254740993
    assert type(old_cells["serial"]) is int
    assert old_cells["start_port"] == 443
    assert type(old_cells["start_port"]) is int
    assert old_cells["asset_owner"] == -9007199254740993
    assert type(old_cells["asset_owner"]) is int
    assert old_cells["port_owner"] == 1.5
    assert type(old_cells["port_owner"]) is float
    assert old_cells["department"] is True
    assert old_cells["asset_department"] == {"kind": "date", "value": "2026-03-04"}

    candidate = _upload(
        client,
        root,
        superuser_token_headers,
        [[address, 443, 443, "否", None, None, None, None, None, None, 2]],
        name="lossless-candidate.xlsx",
    )
    basis = _basis(page, candidate["id"])
    response = _details(
        client,
        root,
        superuser_token_headers,
        {
            "basis": basis,
            "selector": {
                "kind": "records",
                "category": "changed",
                "canonical_ip": address,
                "side": "current",
            },
        },
    )
    assert response.status_code == 200, response.text
    _no_store(response)
    fields = response.json()["records"][0]["fields"]
    assert fields["serial"] == {
        "kind": "number",
        "numeric_type": "integer",
        "value": "9007199254740993",
    }
    assert fields["start_port"] == {
        "kind": "number",
        "numeric_type": "integer",
        "value": "443",
    }
    assert fields["asset_owner"] == {
        "kind": "number",
        "numeric_type": "integer",
        "value": "-9007199254740993",
    }
    assert fields["port_owner"] == {
        "kind": "number",
        "numeric_type": "float",
        "value": "1.5",
    }
    assert fields["department"] is True
    assert fields["asset_department"] == {"kind": "date", "value": "2026-03-04"}
    assert "9007199254740993" in response.text
    assert "-9007199254740993" in response.text
    assert "9007199254740992" not in response.text
    assert "-9007199254740992" not in response.text


def test_replacement_detail_number_projection_preserves_signed_boundary() -> None:
    # The derived XLSX rounds 2**53+1, but this revision API persists original
    # rows; this direct check is supplemental, not a substitute for the API test.
    positive = ledger._detail_cell(9007199254740993)
    negative = ledger._detail_cell(-9007199254740993)
    assert isinstance(positive, ledger.ReplacementDetailNumber)
    assert positive.model_dump() == {
        "kind": "number",
        "numeric_type": "integer",
        "value": "9007199254740993",
    }
    assert isinstance(negative, ledger.ReplacementDetailNumber)
    assert negative.model_dump() == {
        "kind": "number",
        "numeric_type": "integer",
        "value": "-9007199254740993",
    }


def test_replacement_detail_number_tags_reject_malformed_shapes() -> None:
    def record(value: Any) -> ledger.ReplacementDetailRecord:
        return ledger.ReplacementDetailRecord(
            entry_id=uuid.uuid4(),
            position=1,
            canonical_ip="192.0.2.55",
            fields={"serial": value},
        )

    valid = record(
        ledger.ReplacementDetailNumber(
            kind="number",
            numeric_type="integer",
            value="9007199254740993",
        )
    )
    validated = valid.fields["serial"]
    assert isinstance(validated, ledger.ReplacementDetailNumber)
    assert validated.value == "9007199254740993"

    malformed: list[Any] = [
        {"kind": "number", "numeric_type": "integer", "value": "09007199254740993"},
        {"kind": "number", "numeric_type": "integer", "value": "-0"},
        {"kind": "number", "numeric_type": "integer", "value": "+1"},
        {"kind": "number", "numeric_type": "integer", "value": "1.0"},
        {"kind": "number", "numeric_type": "integer", "value": "1e3"},
        {"kind": "number", "numeric_type": "number", "value": "1"},
        {"kind": "number", "numeric_type": "float", "value": "nan"},
        {"kind": "number", "numeric_type": "float", "value": "inf"},
        {"kind": "number", "numeric_type": "float", "value": "1e400"},
        {"kind": "number", "numeric_type": "float", "value": ".5"},
        {
            "kind": "number",
            "numeric_type": "integer",
            "value": "1",
            "extra": True,
        },
        {"kind": "date", "value": "2026-01-02", "extra": True},
        9007199254740993,
        1.5,
    ]
    for value in malformed:
        with pytest.raises(ValidationError):
            record(value)


def test_replacement_details_exclude_archive_and_management_only_changes(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    root, initial = _new_project(client, superuser_token_headers)
    a = ["192.0.2.70", 443, 443, "否", None]
    b = ["192.0.2.71", 443, 443, "否", None]
    base = _upload(
        client, root, superuser_token_headers, [a, b], name="archive-base.xlsx"
    )
    _first_selection(
        client,
        root,
        superuser_token_headers,
        base,
        initial["current_profile_id"],
        "archive-base",
    )

    def current_page() -> dict[str, Any]:
        response = client.get(
            root + "/customer-ledger", headers=superuser_token_headers
        )
        assert response.status_code == 200, response.text
        return cast(dict[str, Any], response.json())

    page = current_page()
    entry_b = next(
        row["entry_id"]
        for row in page["data"]
        if row["canonical_ip"] == "192.0.2.71"
    )
    managed = client.post(
        root + "/customer-ledger/revisions",
        headers={**superuser_token_headers, "Idempotency-Key": "manage-only"},
        json={
            "expected_upload_id": page["upload_id"],
            "expected_revision_id": page["revision_id"],
            "expected_profile_id": page["current_profile_id"],
            "operation": "manage",
            "entry_id": entry_b,
            "fields": {},
            "management": {"owner": "managed", "tags": ["keep"]},
            "reason": "manage only",
        },
    )
    assert managed.status_code == 201, managed.text
    assert managed.json()["input_changed"] is False
    page = current_page()
    identical = _upload(
        client,
        root,
        superuser_token_headers,
        [[*row, *([None] * (len(ledger.HEADERS) - len(row))), "ignored"] for row in [a, b]],
        name="manage-identical.xlsx",
        header_names=[*ledger.HEADERS, "备注"],
    )
    basis = _basis(page, identical["id"])
    preview = client.post(
        root + "/customer-ledger/replacements/preview",
        headers=superuser_token_headers,
        json=basis,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["changed_ip_declarations"] == 0
    assert preview.json()["added_ips"] == 0
    assert preview.json()["removed_ips"] == 0
    for category in ("added", "removed", "changed"):
        response = _details(
            client,
            root,
            superuser_token_headers,
            {
                "basis": basis,
                "selector": {"kind": "groups", "category": category},
            },
        )
        assert response.status_code == 200, response.text
    unchanged = _details(
        client,
        root,
        superuser_token_headers,
        {
            "basis": basis,
            "selector": {"kind": "groups", "category": "changed"},
        },
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["total_groups"] == 0

    entry_a = next(
        row["entry_id"]
        for row in page["data"]
        if row["canonical_ip"] == "192.0.2.70"
    )
    archived = client.post(
        root + "/customer-ledger/revisions",
        headers={**superuser_token_headers, "Idempotency-Key": "archive-one"},
        json={
            "expected_upload_id": page["upload_id"],
            "expected_revision_id": page["revision_id"],
            "expected_profile_id": page["current_profile_id"],
            "operation": "archive",
            "entry_id": entry_a,
            "fields": {},
            "reason": "archive one",
        },
    )
    assert archived.status_code == 201, archived.text
    page = current_page()
    assert page["count"] == 1
    readded = _upload(
        client, root, superuser_token_headers, [a, b], name="archive-readable.xlsx"
    )
    basis = _basis(page, readded["id"])
    preview = client.post(
        root + "/customer-ledger/replacements/preview",
        headers=superuser_token_headers,
        json=basis,
    )
    assert preview.status_code == 200, preview.text
    assert (
        preview.json()["current_record_count"],
        preview.json()["candidate_record_count"],
        preview.json()["added_ips"],
        preview.json()["removed_ips"],
        preview.json()["changed_ip_declarations"],
    ) == (1, 2, 1, 0, 0)
    added = _details(
        client,
        root,
        superuser_token_headers,
        {"basis": basis, "selector": {"kind": "groups", "category": "added"}},
    )
    assert added.status_code == 200, added.text
    assert added.json()["groups"] == [
        {"canonical_ip": "192.0.2.70", "current_records": 0, "candidate_records": 1}
    ]
    both_existing = _upload(
        client,
        root,
        superuser_token_headers,
        [[*b, *([None] * (len(ledger.HEADERS) - len(b))), "ignored"]],
        name="archive-existing.xlsx",
        header_names=[*ledger.HEADERS, "备注"],
    )
    preview = client.post(
        root + "/customer-ledger/replacements/preview",
        headers=superuser_token_headers,
        json={**basis, "candidate_upload_id": both_existing["id"]},
    )
    assert preview.status_code == 200, preview.text
    assert (
        preview.json()["added_ips"],
        preview.json()["removed_ips"],
        preview.json()["changed_ip_declarations"],
    ) == (0, 0, 0)


def test_replacement_details_keep_canonical_ip_and_original_text(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    root, initial = _new_project(client, superuser_token_headers)
    short = "2001:db8::1"
    expanded = "2001:0db8:0000:0000:0000:0000:0000:0001"
    base = _upload(
        client,
        root,
        superuser_token_headers,
        [[short, 443, 443, "否", None, None, None, None, None, None, 1]],
        name="canonical-base.xlsx",
    )
    _first_selection(
        client,
        root,
        superuser_token_headers,
        base,
        initial["current_profile_id"],
        "canonical-base",
    )
    page = client.get(root + "/customer-ledger", headers=superuser_token_headers)
    assert page.status_code == 200, page.text
    page = page.json()
    same = _upload(
        client,
        root,
        superuser_token_headers,
        [[expanded, 443, 443, "否", None, None, None, None, None, None, 1]],
        name="canonical-same.xlsx",
    )
    basis = _basis(page, same["id"])
    preview = client.post(
        root + "/customer-ledger/replacements/preview",
        headers=superuser_token_headers,
        json=basis,
    )
    assert preview.status_code == 200, preview.text
    assert (
        preview.json()["added_ips"],
        preview.json()["removed_ips"],
        preview.json()["changed_ip_declarations"],
    ) == (0, 0, 1)
    changed = _upload(
        client,
        root,
        superuser_token_headers,
        [[expanded, 443, 443, "否", None, None, None, None, None, None, 2]],
        name="canonical-changed.xlsx",
    )
    basis = _basis(page, changed["id"])
    preview = client.post(
        root + "/customer-ledger/replacements/preview",
        headers=superuser_token_headers,
        json=basis,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["changed_ip_declarations"] == 1
    current_side = _details(
        client,
        root,
        superuser_token_headers,
        {
            "basis": basis,
            "selector": {
                "kind": "records",
                "category": "changed",
                "canonical_ip": short,
                "side": "current",
            },
        },
    )
    candidate_side = _details(
        client,
        root,
        superuser_token_headers,
        {
            "basis": basis,
            "selector": {
                "kind": "records",
                "category": "changed",
                "canonical_ip": expanded,
                "side": "candidate",
            },
        },
    )
    assert current_side.status_code == candidate_side.status_code == 200
    assert current_side.json()["canonical_ip"] == short
    assert candidate_side.json()["canonical_ip"] == short
    assert current_side.json()["records"][0]["fields"]["asset_ip"] == short
    assert candidate_side.json()["records"][0]["fields"]["asset_ip"] == expanded
    assert current_side.json()["records"][0]["fields"]["serial"] == {
        "kind": "number",
        "numeric_type": "integer",
        "value": "1",
    }
    assert candidate_side.json()["records"][0]["fields"]["serial"] == {
        "kind": "number",
        "numeric_type": "integer",
        "value": "2",
    }


def _no_store(response: Any) -> None:
    assert response.headers["Cache-Control"] == "private, no-store"


def test_replacement_details_validation_conflicts_denials_and_no_store(
    client: TestClient, setup_ledger: LedgerSetup
) -> None:
    root, headers, _original, _data, _path = setup_ledger
    page = read(client, setup_ledger)
    candidate = _upload(
        client,
        root,
        headers,
        [["192.0.2.80", 443, 443, "否", None]],
        name="validation-candidate.xlsx",
    )
    basis = _basis(page, candidate["id"])
    valid = {"basis": basis, "selector": {"kind": "groups", "category": "added"}}
    success = _details(client, root, headers, valid)
    assert success.status_code == 200, success.text
    _no_store(success)
    me = client.get(settings.API_V1_STR + "/users/me", headers=headers).json()
    assert success.json()["actor_id"] == me["id"]
    assert success.json()["project_id"] == root.split("/")[-1]

    malformed: list[dict[str, Any]] = [
        {**valid, "extra": True},
        {
            "basis": {
                "candidate_upload_id": candidate["id"],
                "expected_revision_id": page["current_revision_id"],
                "expected_profile_id": page["current_profile_id"],
            },
            "selector": valid["selector"],
        },
        {
            "basis": {
                "candidate_upload_id": candidate["id"],
                "expected_upload_id": page["current_upload_id"],
                "expected_profile_id": page["current_profile_id"],
            },
            "selector": valid["selector"],
        },
        {
            "basis": basis,
            "selector": {"kind": "groups", "category": "added", "limit": 26},
        },
        {
            "basis": basis,
            "selector": {"kind": "groups", "category": "added", "limit": 0},
        },
        {
            "basis": basis,
            "selector": {
                "kind": "records",
                "category": "added",
                "canonical_ip": "192.0.2.80",
                "side": "candidate",
                "limit": 11,
            },
        },
        {
            "basis": basis,
            "selector": {
                "kind": "groups",
                "category": "added",
                "canonical_ip": "192.0.2.80",
            },
        },
        {
            "basis": basis,
            "selector": {"kind": "groups", "category": "other"},
        },
        {"basis": basis, "selector": {"kind": "other", "category": "added"}},
        {
            "basis": basis,
            "selector": {
                "kind": "records",
                "category": "added",
                "canonical_ip": "192.0.2.80",
                "side": "both",
            },
        },
        {
            "basis": basis,
            "selector": {
                "kind": "records",
                "category": "added",
                "canonical_ip": "not-an-ip",
                "side": "candidate",
            },
        },
    ]
    for payload in malformed:
        response = _details(client, root, headers, payload)
        assert response.status_code == 422, (payload, response.text)
        _no_store(response)

    sentinel = "sentinel-rejected-detail-value"
    sanitized_payloads: list[dict[str, Any]] = [
        {
            "basis": {**basis, "expected_profile_id": sentinel},
            "selector": valid["selector"],
        },
        {
            "basis": {
                "candidate_upload_id": candidate["id"],
                "expected_upload_id": page["current_upload_id"],
                "expected_revision_id": sentinel,
                "expected_profile_id": page["current_profile_id"],
            },
            "selector": valid["selector"],
        },
        {
            "basis": basis,
            "selector": {"kind": "groups", "category": sentinel},
        },
        {
            "basis": basis,
            "selector": {"kind": sentinel, "category": "added"},
        },
        {
            "basis": basis,
            "selector": {
                "kind": "records",
                "category": "added",
                "canonical_ip": "192.0.2.80",
                "side": sentinel,
            },
        },
        {**valid, "sentinel_extra_key": sentinel},
        {
            "basis": basis,
            "selector": {**valid["selector"], "sentinel_extra_key": sentinel},
        },
    ]
    for payload in sanitized_payloads:
        response = _details(client, root, headers, payload)
        assert response.status_code == 422, (payload, response.text)
        _no_store(response)
        errors = response.json()["detail"]
        assert errors
        for error in errors:
            assert "input" not in error, error
        assert sentinel not in response.text

    invalid_ip = _details(
        client,
        root,
        headers,
        {
            "basis": basis,
            "selector": {
                "kind": "records",
                "category": "added",
                "canonical_ip": "not-an-ip",
                "side": "candidate",
            },
        },
    )
    assert invalid_ip.json()["detail"]["code"] == "ledger_diff_selector_invalid"

    wrong_group = _details(
        client,
        root,
        headers,
        {
            "basis": basis,
            "selector": {
                "kind": "records",
                "category": "added",
                "canonical_ip": "2001:db8:10::20",
                "side": "current",
            },
        },
    )
    assert wrong_group.status_code == 404, wrong_group.text
    assert wrong_group.json()["detail"]["code"] == "ledger_diff_group_not_found"
    _no_store(wrong_group)

    stale = _details(
        client,
        root,
        headers,
        {**valid, "basis": {**basis, "expected_upload_id": str(uuid.uuid4())}},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "ledger_version_conflict"
    _no_store(stale)
    stale_profile = _details(
        client,
        root,
        headers,
        {**valid, "basis": {**basis, "expected_profile_id": str(uuid.uuid4())}},
    )
    assert stale_profile.status_code == 409, stale_profile.text
    assert stale_profile.json()["detail"]["code"] == "ledger_profile_changed"
    _no_store(stale_profile)

    other_root, _other_initial = _new_project(client, headers)
    other_candidate = _upload(
        client,
        other_root,
        headers,
        [["192.0.2.81", 443, 443, "否", None]],
        name="other-project.xlsx",
    )
    inaccessible = _details(
        client,
        root,
        headers,
        {**valid, "basis": _basis(page, other_candidate["id"])},
    )
    assert inaccessible.status_code == 404, inaccessible.text
    assert inaccessible.json()["detail"]["code"] == "ledger_upload_not_found"
    _no_store(inaccessible)

    viewer = _create_member(
        client, headers, project_id=root.split("/")[-1], roles=["viewer"]
    )
    viewer_read = _details(client, root, viewer, valid)
    assert viewer_read.status_code == 200, viewer_read.text
    _no_store(viewer_read)

    email = random_email()
    password = random_lower_string()
    created = client.post(
        settings.API_V1_STR + "/users/",
        headers=headers,
        json={"email": email, "password": password},
    )
    assert created.status_code == 200, created.text
    outsider = user_authentication_headers(
        client=client, email=email, password=password
    )
    denied = _details(client, root, outsider, valid)
    assert denied.status_code == 404, denied.text
    _no_store(denied)


def test_replacement_details_skip_bounds(
    client: TestClient, setup_ledger: LedgerSetup
) -> None:
    root, headers, _original, _data, _path = setup_ledger
    page = read(client, setup_ledger)
    candidate = _upload(
        client,
        root,
        headers,
        [["192.0.2.86", 443, 443, "否", None]],
        name="skip-bounds.xlsx",
    )
    basis = _basis(page, candidate["id"])
    maximum = ledger.DETAIL_SKIP_MAX
    assert maximum == 9007199254740991

    def selector(kind: str, skip: int) -> dict[str, Any]:
        if kind == "groups":
            return {"kind": "groups", "category": "added", "skip": skip}
        return {
            "kind": "records",
            "category": "added",
            "canonical_ip": "192.0.2.86",
            "side": "candidate",
            "skip": skip,
        }

    for kind in ("groups", "records"):
        accepted = _details(
            client,
            root,
            headers,
            {"basis": basis, "selector": selector(kind, maximum)},
        )
        assert accepted.status_code == 200, accepted.text
        _no_store(accepted)
        if kind == "groups":
            assert accepted.json()["total_groups"] == 1
            assert accepted.json()["groups"] == []
        else:
            assert accepted.json()["total_records"] == 1
            assert accepted.json()["records"] == []
        below = _details(
            client,
            root,
            headers,
            {"basis": basis, "selector": selector(kind, maximum - 1)},
        )
        assert below.status_code == 200, below.text
        _no_store(below)
        assert (
            below.json()["groups"] == []
            if kind == "groups"
            else below.json()["records"] == []
        )
        for rejected in (-1, maximum + 1):
            response = _details(
                client,
                root,
                headers,
                {"basis": basis, "selector": selector(kind, rejected)},
            )
            assert response.status_code == 422, (kind, rejected, response.text)
            _no_store(response)
            errors = response.json()["detail"]
            assert errors
            for error in errors:
                assert "input" not in error, error


def test_replacement_details_unauthenticated_and_inactive_denial(
    client: TestClient, setup_ledger: LedgerSetup
) -> None:
    root, headers, _original, _data, _path = setup_ledger
    page = read(client, setup_ledger)
    candidate = _upload(
        client,
        root,
        headers,
        [["192.0.2.87", 443, 443, "否", None]],
        name="denial-candidate.xlsx",
    )
    valid = {
        "basis": _basis(page, candidate["id"]),
        "selector": {"kind": "groups", "category": "added"},
    }
    anonymous = _details(client, root, {}, valid)
    assert anonymous.status_code == 401, anonymous.text
    _no_store(anonymous)

    email = random_email()
    password = random_lower_string()
    created = client.post(
        settings.API_V1_STR + "/users/",
        headers=headers,
        json={"email": email, "password": password},
    )
    assert created.status_code == 200, created.text
    inactive_headers = user_authentication_headers(
        client=client, email=email, password=password
    )
    with Session(engine) as db:
        user = db.exec(select(User).where(User.email == email)).one()
        user.is_active = False
        db.add(user)
        db.commit()
    inactive = _details(client, root, inactive_headers, valid)
    assert inactive.status_code == 400, inactive.text
    assert inactive.json() == {"detail": "Inactive user"}
    _no_store(inactive)


def test_replacement_details_unexpected_failures_are_sanitized_and_no_store(
    client: TestClient,
    setup_ledger: LedgerSetup,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    root, headers, _original, _data, _path = setup_ledger
    page = read(client, setup_ledger)
    candidate = _upload(
        client,
        root,
        headers,
        [["192.0.2.88", 443, 443, "否", None]],
        name="failure-candidate.xlsx",
    )
    body = {
        "basis": _basis(page, candidate["id"]),
        "selector": {"kind": "groups", "category": "added"},
    }
    secret = "sentinel-unexpected-failure-value"

    def crash(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise RuntimeError(secret)

    monkeypatch.setattr(ledger, "replacement_details", crash)
    with caplog.at_level(logging.ERROR, logger="app.api.routes.customer_ledger"):
        raised = _details(client, root, headers, body)
    assert raised.status_code == 500, raised.text
    assert raised.json() == {"detail": "Internal Server Error"}
    assert secret not in raised.text
    _no_store(raised)
    assert any(
        record.exc_info for record in caplog.records
    ), "unexpected failure must be reported with a traceback"

    monkeypatch.setattr(
        ledger, "replacement_details", lambda *_args, **_kwargs: object()
    )
    invalid_response = _details(client, root, headers, body)
    assert invalid_response.status_code == 500, invalid_response.text
    assert invalid_response.json() == {"detail": "Internal Server Error"}
    assert secret not in invalid_response.text
    _no_store(invalid_response)

    def failing_db() -> NoReturn:
        raise RuntimeError(secret)

    caplog.clear()
    app.dependency_overrides[get_db] = failing_db
    try:
        with caplog.at_level(logging.ERROR, logger="app.api.routes.customer_ledger"):
            dependency_failure = _details(client, root, headers, body)
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert dependency_failure.status_code == 500, dependency_failure.text
    assert dependency_failure.json() == {"detail": "Internal Server Error"}
    assert secret not in dependency_failure.text
    _no_store(dependency_failure)
    assert any(record.exc_info for record in caplog.records)


def test_replacement_details_revision_only_basis_conflict(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    root, initial = _new_project(client, superuser_token_headers)
    address = "192.0.2.85"
    base = _upload(
        client,
        root,
        superuser_token_headers,
        [[address, 443, 443, "否", None]],
        name="revision-base.xlsx",
    )
    _first_selection(
        client,
        root,
        superuser_token_headers,
        base,
        initial["current_profile_id"],
        "revision-base",
    )
    page = client.get(root + "/customer-ledger", headers=superuser_token_headers)
    assert page.status_code == 200, page.text
    page = page.json()
    revised = client.post(
        root + "/customer-ledger/revisions",
        headers={**superuser_token_headers, "Idempotency-Key": "revision-only"},
        json={
            "expected_upload_id": page["upload_id"],
            "expected_revision_id": page["revision_id"],
            "expected_profile_id": page["current_profile_id"],
            "operation": "update",
            "entry_id": page["data"][0]["entry_id"],
            "fields": {"asset_owner": "revision owner"},
            "reason": "revision only conflict fixture",
        },
    )
    assert revised.status_code == 201, revised.text
    page = client.get(root + "/customer-ledger", headers=superuser_token_headers)
    assert page.status_code == 200, page.text
    page = page.json()
    assert page["revision_id"] is not None
    candidate = _upload(
        client,
        root,
        superuser_token_headers,
        [[address, 8443, 8443, "否", None]],
        name="revision-candidate.xlsx",
    )
    basis = _basis(page, candidate["id"])
    valid = {"basis": basis, "selector": {"kind": "groups", "category": "changed"}}
    accepted = _details(client, root, superuser_token_headers, valid)
    assert accepted.status_code == 200, accepted.text
    _no_store(accepted)
    stale = _details(
        client,
        root,
        superuser_token_headers,
        {
            **valid,
            "basis": {
                **basis,
                "expected_revision_id": str(uuid.uuid4()),
            },
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "ledger_version_conflict"
    _no_store(stale)


def test_replacement_details_reads_do_not_write_and_damaged_source_fails(
    client: TestClient, setup_ledger: LedgerSetup
) -> None:
    root, headers, original, _data, path = setup_ledger
    page = read(client, setup_ledger)
    candidate = _upload(
        client,
        root,
        headers,
        [["192.0.2.90", 443, 443, "否", None]],
        name="zero-write.xlsx",
    )
    basis = _basis(page, candidate["id"])
    project_id = uuid.UUID(root.split("/")[-1])

    def counts() -> tuple[int, int, int, int, int]:
        with Session(engine) as db:
            return (
                len(db.exec(select(CustomerUpload)).all()),
                len(db.exec(select(Artifact)).all()),
                len(db.exec(select(CustomerLedgerRevision)).all()),
                len(
                    db.exec(
                        select(CustomerUploadReplacement).where(
                            CustomerUploadReplacement.project_id == project_id
                        )
                    ).all()
                ),
                len(db.exec(select(AuditEvent)).all()),
            )

    before = counts()
    files = set(path.rglob("*.xlsx"))
    groups = _details(
        client,
        root,
        headers,
        {"basis": basis, "selector": {"kind": "groups", "category": "added"}},
    )
    records = _details(
        client,
        root,
        headers,
        {
            "basis": basis,
            "selector": {
                "kind": "records",
                "category": "added",
                "canonical_ip": "192.0.2.90",
                "side": "candidate",
            },
        },
    )
    assert groups.status_code == records.status_code == 200
    assert groups.json()["total_groups"] == 1
    assert records.json()["total_records"] == 1
    after = counts()
    assert after == before
    assert set(path.rglob("*.xlsx")) == files
    assert read(client, setup_ledger)["upload_id"] == original["id"]

    with Session(engine) as db:
        upload = db.get(CustomerUpload, uuid.UUID(page["current_upload_id"]))
        assert upload is not None
        artifact = db.get(Artifact, upload.artifact_id)
        assert artifact is not None
        (path / artifact.storage_key).unlink()
    damaged = _details(
        client,
        root,
        headers,
        {"basis": basis, "selector": {"kind": "groups", "category": "added"}},
    )
    assert damaged.status_code == 500, damaged.text
    assert damaged.json()["detail"]["code"] == "ledger_source_invalid"
    _no_store(damaged)
    with Session(engine) as db:
        project = db.get(Project, project_id)
        assert project is not None
        assert project.current_customer_upload_id == uuid.UUID(original["id"])
