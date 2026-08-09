from __future__ import annotations

import io
import re
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient
from openpyxl import Workbook  # type: ignore[import-untyped]
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlalchemy import event
from sqlmodel import Session, col, func, select

from app.core.config import settings
from app.core.db import engine
from app.domain.cloudatlas_sources import CloudAtlasFingerprint, OctobusCloudAtlasClient
from app.domain.models import (
    Finding,
    FindingOccurrence,
    FindingOccurrenceObservation,
    FindingOccurrenceSnapshot,
    FindingTransition,
    FindingTransitionObservation,
    FindingTransitionSnapshot,
    GovernanceRun,
    Observation,
    ObservationResourceLink,
    Resource,
    RunStep,
)
from app.governance_runner import main as run_governance_runner
from tests.api.routes.test_governance_runs import (
    _create_project,
    _prepare_ready_project,
    _runner_environment,
)

REQUIRED_HEADERS = ["资产IP", "起始端口", "结束端口", "是否web界面", "web界面url"]
XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
VALIDATED_FINGERPRINT = "1" * 64
FIXTURE_SOURCE_RECORD_COUNT = 10_000
CUSTOMER_RECORD_COUNT = 5_000
CLOUDATLAS_RECORD_COUNT = 5_000
CUSTOMER_ONLY_RESOURCE_COUNT = 1_500
CLOUDATLAS_ONLY_RESOURCE_COUNT = 1_500
MATCHED_RESOURCE_COUNT = 2_500
RESOURCE_COUNT = (
    MATCHED_RESOURCE_COUNT
    + CUSTOMER_ONLY_RESOURCE_COUNT
    + CLOUDATLAS_ONLY_RESOURCE_COUNT
)
FINDING_COUNT = CUSTOMER_ONLY_RESOURCE_COUNT + CLOUDATLAS_ONLY_RESOURCE_COUNT
APPEARING_OBSERVATION_COUNT = 3_500
MAPPED_IPV6_OBSERVATION_COUNT = 1_500
IPV6_OBSERVATION_COUNT = 1_500
DB_BATCH_SIZE = 500
EXPECTED_STAGE4_STEP_HASHES = {
    "NORMALIZE": "93729f7e64354643f824009e391fb937f700824a65014f3d5c6a5f88e0f5e1a3",
    "RESOLVE": "eefd11da50ca4239014db6ff6e3b910e4fc95ce81467de074bd28ff5ef26776e",
    "CHECK_FINDINGS": "8b99012d6300463b8b0044f32bba233589b6324c78b5cb0e5501de0a24aaee65",
    "PUBLISH": "fd799dda8cc7e3acf48a7d9556727294db1db9410457c02335c1aa468c716311",
}


class QueryTrace:
    def __init__(self) -> None:
        self.insert_counts: defaultdict[str, int] = defaultdict(int)
        self.selects: defaultdict[str, list[str]] = defaultdict(list)

    def listener(
        self,
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        normalized = " ".join(statement.lower().split())
        for table in (
            "observations",
            "resources",
            "observation_resource_links",
            "findings",
            "finding_occurrences",
            "finding_transitions",
            "finding_occurrence_observations",
            "finding_occurrence_snapshots",
            "finding_transition_observations",
            "finding_transition_snapshots",
        ):
            if _has_sql_table(normalized, "insert", table):
                self.insert_counts[table] += 1
        for table in (
            "observations",
            "resources",
            "observation_resource_links",
            "findings",
        ):
            if _has_sql_table(normalized, "from", table):
                self.selects[table].append(normalized)


def _has_sql_table(statement: str, operation: str, table: str) -> bool:
    if operation == "insert":
        return bool(
            re.search(rf"insert into (?:\"{table}\"|{table})(?:\s|\()", statement)
        )
    return bool(re.search(rf"from (?:\"{table}\"|{table})(?:\s|$)", statement))


def _ipv4(first_octet: int, index: int) -> str:
    return f"{first_octet}.{index // 256}.{index % 256}.1"


def _fixture_records() -> tuple[list[str], list[dict[str, str]]]:
    common_ipv4 = [_ipv4(10, index) for index in range(2_000)]
    customer_only_ipv4 = [_ipv4(172, index) for index in range(1_000)]
    cloudatlas_only_ipv4 = [_ipv4(192, index) for index in range(1_000)]
    common_ipv6 = [f"2001:db8:1::{index + 1}" for index in range(500)]
    customer_only_ipv6 = [f"2001:db8:2::{index + 1}" for index in range(500)]
    cloudatlas_only_ipv6 = [f"2001:db8:3::{index + 1}" for index in range(500)]

    customer_ips = (
        common_ipv4
        + customer_only_ipv4
        + common_ipv6
        + customer_only_ipv6
        + common_ipv4[:500]
        + customer_only_ipv4[:250]
        + common_ipv6[:250]
    )
    cloudatlas_common_ipv4 = [
        f"::ffff:{ip}" if index < 1_000 else ip
        for index, ip in enumerate(common_ipv4)
    ]
    cloudatlas_ips = (
        cloudatlas_common_ipv4
        + cloudatlas_only_ipv4
        + common_ipv6
        + cloudatlas_only_ipv6
        + cloudatlas_common_ipv4[:500]
        + cloudatlas_only_ipv4[:250]
        + common_ipv6[:250]
    )
    assert len(customer_ips) == CUSTOMER_RECORD_COUNT
    assert len(cloudatlas_ips) == CLOUDATLAS_RECORD_COUNT
    return customer_ips, [
        {"id": f"cloud-{index + 1}", "ip": ip, "status": "valid"}
        for index, ip in enumerate(cloudatlas_ips)
    ]


def _workbook_bytes(ips: list[str]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(REQUIRED_HEADERS)
    for ip in ips:
        worksheet.append([ip, 443, 443, "是", "example.test"])
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _count(
    session: Session, model: type[Any], *conditions: Any
) -> int:
    statement = select(func.count()).select_from(model)
    for condition in conditions:
        statement = statement.where(condition)
    return int(session.exec(statement).one())


def _run_steps(
    session: Session, run_id: uuid.UUID
) -> dict[str, str | None]:
    return {
        step.step_code: step.output_hash
        for step in session.exec(
            select(RunStep).where(RunStep.governance_run_id == run_id)
        ).all()
    }


def _max_batches(record_count: int) -> int:
    return (record_count + DB_BATCH_SIZE - 1) // DB_BATCH_SIZE


def _set_runner_environment(
    monkeypatch: MonkeyPatch,
    *,
    project: dict[str, object],
    upload: dict[str, object],
    source: dict[str, object],
    trigger_id: str,
    session_seed: str,
) -> None:
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id=trigger_id,
        session_seed=session_seed,
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)


def test_stage4_10k_pipeline_is_deterministic_and_batched(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))

    customer_ips, cloudatlas_items = _fixture_records()
    cloudatlas_page_calls: list[tuple[int, int]] = []
    fingerprint = CloudAtlasFingerprint(VALIDATED_FINGERPRINT)
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "current_fingerprint",
        lambda _client, _source: fingerprint,
    )
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "validate_read",
        lambda _client, _source, *, capset_token: fingerprint,
    )

    def list_page(
        _client: object,
        _source: object,
        *,
        capset_token: str,
        page: int,
        size: int,
    ) -> dict[str, object]:
        del capset_token
        cloudatlas_page_calls.append((page, size))
        start = (page - 1) * size
        return {
            "items": cloudatlas_items[start : start + size],
            "page": page,
            "size": size,
            "total": len(cloudatlas_items),
        }

    monkeypatch.setattr(OctobusCloudAtlasClient, "list_ip_assets_page", list_page)

    project = _create_project(client, superuser_token_headers)
    _, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    upload_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=superuser_token_headers,
        files={
            "file": (
                "customer-10k.xlsx",
                _workbook_bytes(customer_ips),
                XLSX_MEDIA_TYPE,
            )
        },
    )
    assert upload_response.status_code == 201, upload_response.text
    upload = cast(dict[str, object], upload_response.json())
    select_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads/{upload['id']}/select",
        headers=superuser_token_headers,
    )
    assert select_response.status_code == 200, select_response.text

    _set_runner_environment(
        monkeypatch,
        project=project,
        upload=upload,
        source=source,
        trigger_id="stage4-10k-first",
        session_seed="stage4-10k-first-session",
    )
    trace = QueryTrace()
    event.listen(engine, "before_cursor_execute", trace.listener)
    try:
        assert run_governance_runner() == 0
    finally:
        event.remove(engine, "before_cursor_execute", trace.listener)

    with Session(engine) as session:
        first_run = session.exec(
            select(GovernanceRun).where(
                GovernanceRun.project_id == uuid.UUID(str(project["id"])),
                GovernanceRun.trigger_id == "stage4-10k-first",
            )
        ).one()
        first_run_id = first_run.id
        assert _count(session, Observation, Observation.governance_run_id == first_run_id) == FIXTURE_SOURCE_RECORD_COUNT
        assert _count(
            session,
            Observation,
            Observation.governance_run_id == first_run_id,
            col(Observation.raw_ip).like("::ffff:%"),
        ) == MAPPED_IPV6_OBSERVATION_COUNT
        assert _count(
            session,
            Observation,
            Observation.governance_run_id == first_run_id,
            col(Observation.raw_ip).like("2001:db8:1:%"),
        ) == IPV6_OBSERVATION_COUNT
        assert _count(session, Resource, Resource.project_id == first_run.project_id) == RESOURCE_COUNT
        assert _count(
            session,
            ObservationResourceLink,
            ObservationResourceLink.governance_run_id == first_run_id,
        ) == FIXTURE_SOURCE_RECORD_COUNT
        assert _count(session, Finding, Finding.project_id == first_run.project_id) == FINDING_COUNT
        assert _count(
            session,
            FindingOccurrence,
            FindingOccurrence.governance_run_id == first_run_id,
        ) == FINDING_COUNT
        assert _count(
            session,
            FindingTransition,
            FindingTransition.governance_run_id == first_run_id,
        ) == FINDING_COUNT
        assert _count(
            session,
            FindingOccurrenceObservation,
            FindingOccurrenceObservation.governance_run_id == first_run_id,
        ) == APPEARING_OBSERVATION_COUNT
        assert _count(
            session,
            FindingTransitionObservation,
            FindingTransitionObservation.governance_run_id == first_run_id,
        ) == APPEARING_OBSERVATION_COUNT
        assert _count(
            session,
            FindingOccurrenceSnapshot,
            FindingOccurrenceSnapshot.governance_run_id == first_run_id,
        ) == FINDING_COUNT * 2
        assert _count(
            session,
            FindingTransitionSnapshot,
            FindingTransitionSnapshot.governance_run_id == first_run_id,
        ) == FINDING_COUNT * 2
        first_hashes = _run_steps(session, first_run_id)

    assert {
        step_code: first_hashes[step_code]
        for step_code in EXPECTED_STAGE4_STEP_HASHES
    } == EXPECTED_STAGE4_STEP_HASHES
    assert len(cloudatlas_page_calls) == 25
    assert {size for _, size in cloudatlas_page_calls} == {200}
    assert trace.insert_counts["observations"] <= _max_batches(FIXTURE_SOURCE_RECORD_COUNT)
    assert trace.insert_counts["resources"] <= _max_batches(RESOURCE_COUNT)
    assert trace.insert_counts["observation_resource_links"] <= _max_batches(
        FIXTURE_SOURCE_RECORD_COUNT
    )
    assert trace.insert_counts["findings"] <= _max_batches(FINDING_COUNT)
    assert trace.insert_counts["finding_occurrences"] <= _max_batches(FINDING_COUNT)
    assert trace.insert_counts["finding_transitions"] <= _max_batches(FINDING_COUNT)
    assert trace.insert_counts["finding_occurrence_observations"] <= _max_batches(
        APPEARING_OBSERVATION_COUNT
    )
    assert trace.insert_counts["finding_occurrence_snapshots"] <= _max_batches(
        FINDING_COUNT * 2
    )
    assert trace.insert_counts["finding_transition_observations"] <= _max_batches(
        APPEARING_OBSERVATION_COUNT
    )
    assert trace.insert_counts["finding_transition_snapshots"] <= _max_batches(
        FINDING_COUNT * 2
    )

    finding_selects = trace.selects["findings"]
    assert len(finding_selects) == 1
    assert "resource_id in" in finding_selects[0]
    assert len(trace.selects["resources"]) == 2
    assert all("canonical_key in" in statement for statement in trace.selects["resources"])
    assert len(trace.selects["observations"]) == 3
    assert len(trace.selects["observation_resource_links"]) == 3

    assets_first = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets?limit=100",
        headers=superuser_token_headers,
    )
    findings_first = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/findings?limit=100",
        headers=superuser_token_headers,
    )
    assert assets_first.status_code == 200, assets_first.text
    assert findings_first.status_code == 200, findings_first.text
    first_asset_order = [item["canonical_ip"] for item in assets_first.json()["data"]]
    first_finding_order = [item["id"] for item in findings_first.json()["data"]]
    assert first_asset_order == sorted(first_asset_order, key=_ip_sort_key)

    _set_runner_environment(
        monkeypatch,
        project=project,
        upload=upload,
        source=source,
        trigger_id="stage4-10k-second",
        session_seed="stage4-10k-second-session",
    )
    assert run_governance_runner() == 0

    with Session(engine) as session:
        second_run = session.exec(
            select(GovernanceRun).where(
                GovernanceRun.project_id == uuid.UUID(str(project["id"])),
                GovernanceRun.trigger_id == "stage4-10k-second",
            )
        ).one()
        assert _run_steps(session, second_run.id) == first_hashes
        assert _count(session, Observation, Observation.governance_run_id == second_run.id) == FIXTURE_SOURCE_RECORD_COUNT
        assert _count(session, ObservationResourceLink, ObservationResourceLink.governance_run_id == second_run.id) == FIXTURE_SOURCE_RECORD_COUNT
        assert _count(session, FindingOccurrence, FindingOccurrence.governance_run_id == second_run.id) == FINDING_COUNT
        assert _count(session, FindingTransition, FindingTransition.governance_run_id == second_run.id) == 0

    assets_second = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets?limit=100",
        headers=superuser_token_headers,
    )
    findings_second = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/findings?limit=100",
        headers=superuser_token_headers,
    )
    assert assets_second.status_code == 200, assets_second.text
    assert findings_second.status_code == 200, findings_second.text
    assert [item["canonical_ip"] for item in assets_second.json()["data"]] == first_asset_order
    assert [item["id"] for item in findings_second.json()["data"]] == first_finding_order


def _ip_sort_key(value: object) -> tuple[int, int]:
    import ipaddress

    address = ipaddress.ip_address(cast(str, value))
    return address.version, int(address)
