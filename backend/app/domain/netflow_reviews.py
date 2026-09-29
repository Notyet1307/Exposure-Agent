"""Version-pinned component review material; never an approval or asset mutation."""

import hashlib
import ipaddress
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain.ip_consistency import normalize_ip
from app.domain.models import Project
from app.domain.netflow_common import (
    deny,
    new_output_directory,
    operation_result,
    record_operation,
    seal_artifacts,
    verify_receipt,
)
from app.domain.netflow_models import NetFlowAnalysis, NetFlowFeedbackRevision
from app.domain.netflow_processing import (
    analysis_material,
    context_for,
    validate_context,
)
from app.integrations import netflow_processor as processor

MaterialStatus = Literal[
    "AWAITING_FEEDBACK",
    "MATERIAL_INCOMPLETE",
    "INVALID_MATERIAL",
    "MATERIAL_CONFLICT",
    "AWAITING_DEPENDENCY_MATERIAL",
    "FIELDS_COMPLETE_PENDING_REVIEW",
]


class ResponsePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1, max_length=256)
    provided_by: str | None
    submitted_at: str | None
    answers: dict[str, Any]
    note_checks: list[dict[str, Any]]


class FeedbackPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_parent_id: uuid.UUID
    responses: list[ResponsePatch] = Field(max_length=100)
    human_note: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def unique_tasks(self) -> FeedbackPatch:
        if len({item.task_id for item in self.responses}) != len(self.responses):
            raise ValueError("duplicate task patch")
        return self


class Identity(BaseModel):
    contract_version: Literal["netflow-correlation-v1"] = "netflow-correlation-v1"
    project_id: uuid.UUID
    analysis_id: uuid.UUID
    dataset_id: uuid.UUID
    context_revision_id: uuid.UUID
    network_namespace: str
    test_fixture: bool
    provenance: dict[str, Any]


class Author(BaseModel):
    actor_id: uuid.UUID
    submitted_at: datetime
    feedback_revision_id: uuid.UUID


class TaskMaterial(BaseModel):
    task_id: str
    task: dict[str, Any]
    schema_version: str
    answer_schema: dict[str, Any]
    material_status: MaterialStatus
    declared_answers: dict[str, Any]
    provider_claim: dict[str, Any]
    authenticated_author: Author | None
    missing_fields: list[str]
    field_errors: list[dict[str, Any]]
    blocked_by: list[str]
    note_checks: list[dict[str, Any]]
    model_hints: list[dict[str, Any]]
    next_action: str
    review_required: Literal[True] = True
    task_closed: Literal[False] = False
    facts_changed: Literal[False] = False
    external_reachability: Literal["NOT_VERIFIED"] = "NOT_VERIFIED"


class TaskPage(Identity):
    feedback_revision_id: uuid.UUID
    binding: dict[str, Any]
    data: list[TaskMaterial]
    count: int
    skip: int
    limit: int
    total_tasks: int
    state_counts: dict[str, int]


class TaskDetail(Identity):
    feedback_revision_id: uuid.UUID
    binding: dict[str, Any]
    material: TaskMaterial
    dependencies: list[TaskMaterial]


class FeedbackPublic(Identity):
    feedback_revision_id: uuid.UUID
    parent_id: uuid.UUID | None
    revision: int
    system_generated: bool
    authenticated_actor_id: uuid.UUID | None
    authenticated_submitted_at: datetime
    human_note: str | None
    binding: dict[str, Any]
    schema_version: str
    submission: dict[str, Any]
    summary: dict[str, Any]
    response_authors: dict[str, Author]
    review_required: Literal[True] = True
    task_closed: Literal[False] = False
    facts_changed: Literal[False] = False


class Peer(BaseModel):
    peer_key: str
    canonical_ip: str
    family: Literal[4, 6]
    protocol_number: int
    peer_port: int | None
    source_record_count: int
    retained_count: int
    omitted_count: int
    is_local_candidate: Literal[False] = False
    original: dict[str, Any]


class PeerPage(Identity):
    data: list[Peer]
    count: int
    skip: int
    limit: int
    total_peers: int
    total_peer_records: int


class EvidenceRef(BaseModel):
    reference: str
    side: Literal["source", "peer"]
    object_key: str | None
    peer_key: str | None


class EvidencePage(Identity):
    side: Literal["source", "peer"]
    object_key: str | None
    peer_key: str | None
    data: list[EvidenceRef]
    count: int
    skip: int
    limit: int
    retained_count: int
    omitted_count: int
    source_record_count: int
    input_sha256: str
    artifact_sha256: str
    component_binding: dict[str, Any]


def _identity(
    analysis: NetFlowAnalysis, bundle: processor.ProcessorBundle
) -> dict[str, Any]:
    return {
        "project_id": analysis.project_id,
        "analysis_id": analysis.id,
        "dataset_id": analysis.dataset_id,
        "context_revision_id": analysis.context_revision_id,
        "network_namespace": analysis.network_namespace,
        "test_fixture": analysis.test_fixture,
        "provenance": bundle.manifest,
    }


def _revision(
    session: Session,
    project: Project,
    analysis: NetFlowAnalysis,
    revision_id: uuid.UUID | None,
) -> NetFlowFeedbackRevision:
    query = select(NetFlowFeedbackRevision).where(
        NetFlowFeedbackRevision.analysis_id == analysis.id,
        NetFlowFeedbackRevision.project_id == project.id,
        NetFlowFeedbackRevision.tenant_id == project.tenant_id,
    )
    if revision_id is not None:
        query = query.where(NetFlowFeedbackRevision.id == revision_id)
    row = session.exec(
        query.order_by(col(NetFlowFeedbackRevision.revision).desc()).limit(1)
    ).first()
    if row is None:
        deny("review_task_not_found", 404)
    return row


def _feedback(
    session: Session,
    project: Project,
    analysis: NetFlowAnalysis,
    bundle: processor.ProcessorBundle,
    row: NetFlowFeedbackRevision,
) -> processor.FeedbackBundle:
    root = verify_receipt(session, project, row.artifact_manifest)
    feedback = processor.load_feedback(
        root,
        namespace=analysis.network_namespace,
        allow_test=settings.NETFLOW_ALLOW_TEST_FIXTURES,
    )
    manifest = bundle.manifest
    binding = {
        key: manifest[key]
        for key in (
            "tenant_id",
            "project_id",
            "dataset_id",
            "network_namespace",
            "test_fixture",
        )
    }
    binding.update(
        source_run_id=manifest["run_id"], source_input_sha256=manifest["input_sha256"]
    )
    for field, name in (
        ("source_manifest_sha256", "analysis/manifest.json"),
        ("review_summary_sha256", "review/summary.json"),
        ("review_tasks_sha256", "review/review-tasks.jsonl"),
    ):
        binding[field] = hashlib.sha256((bundle.root / name).read_bytes()).hexdigest()
    binding["source_observations_sha256"] = next(
        item["sha256"]
        for item in manifest["artifacts"]
        if item["path"] == "observations.jsonl"
    )
    tasks = {task["task_id"]: task for task in bundle.tasks}
    if (
        feedback.submission["binding"] != binding
        or feedback.summary["binding"] != binding
        or len(feedback.progress) != len(tasks)
        or {item["task"]["task_id"] for item in feedback.progress} != set(tasks)
        or any(
            item["task"] != tasks[item["task"]["task_id"]] for item in feedback.progress
        )
    ):
        deny("netflow_artifact_integrity_failed")
    return feedback


def _authors(row: NetFlowFeedbackRevision) -> dict[str, Author]:
    return {
        key: Author.model_validate(value)
        for key, value in (row.provider_claim or {}).get("response_authors", {}).items()
    }


def _material(
    progress: dict[str, Any],
    feedback: processor.FeedbackBundle,
    authors: dict[str, Author],
) -> TaskMaterial:
    task = progress["task"]
    return TaskMaterial(
        task_id=task["task_id"],
        task=task,
        schema_version=feedback.submission["schema_version"],
        answer_schema=processor.answer_schema(task["task_kind"]),
        material_status=progress["material_status"],
        declared_answers=progress["answers"],
        provider_claim={
            "provided_by": progress["provided_by"],
            "submitted_at": progress["submitted_at"],
        },
        authenticated_author=authors.get(task["task_id"]),
        **{
            key: progress[key]
            for key in (
                "missing_fields",
                "field_errors",
                "blocked_by",
                "note_checks",
                "model_hints",
                "next_action",
            )
        },
    )


def feedback_public(
    analysis: NetFlowAnalysis,
    bundle: processor.ProcessorBundle,
    row: NetFlowFeedbackRevision,
    feedback: processor.FeedbackBundle,
) -> FeedbackPublic:
    return FeedbackPublic(
        **_identity(analysis, bundle),
        feedback_revision_id=row.id,
        parent_id=row.parent_id,
        revision=row.revision,
        system_generated=row.system_generated,
        authenticated_actor_id=row.created_by,
        authenticated_submitted_at=row.created_at,
        human_note=row.human_note,
        binding=feedback.submission["binding"],
        schema_version=feedback.submission["schema_version"],
        submission=feedback.submission,
        summary=feedback.summary,
        response_authors=_authors(row),
    )


def read_feedback(
    session: Session,
    project: Project,
    analysis_id: uuid.UUID,
    revision_id: uuid.UUID | None = None,
) -> FeedbackPublic:
    analysis, bundle = analysis_material(session, project, analysis_id)
    row = _revision(session, project, analysis, revision_id)
    return feedback_public(
        analysis, bundle, row, _feedback(session, project, analysis, bundle, row)
    )


def read_tasks(
    session: Session,
    project: Project,
    analysis_id: uuid.UUID,
    *,
    feedback_revision_id: uuid.UUID | None,
    task_scope: str | None,
    task_kind: str | None,
    material_status: MaterialStatus | None,
    object_key: str | None,
    skip: int,
    limit: int,
) -> TaskPage:
    analysis, bundle = analysis_material(session, project, analysis_id)
    row = _revision(session, project, analysis, feedback_revision_id)
    feedback = _feedback(session, project, analysis, bundle, row)
    selected = [
        item
        for item in feedback.progress
        if (task_scope is None or item["task"]["task_scope"] == task_scope)
        and (task_kind is None or item["task"]["task_kind"] == task_kind)
        and (material_status is None or item["material_status"] == material_status)
        and (object_key is None or item["task"]["object_key"] == object_key)
    ]
    selected.sort(
        key=lambda item: (item["task"]["work_order"], item["task"]["task_id"])
    )
    authors = _authors(row)
    return TaskPage(
        **_identity(analysis, bundle),
        feedback_revision_id=row.id,
        binding=feedback.submission["binding"],
        data=[
            _material(item, feedback, authors) for item in selected[skip : skip + limit]
        ],
        count=len(selected),
        skip=skip,
        limit=limit,
        total_tasks=len(bundle.tasks),
        state_counts=feedback.summary["state_counts"],
    )


def read_task(
    session: Session,
    project: Project,
    analysis_id: uuid.UUID,
    task_id: str,
    feedback_revision_id: uuid.UUID | None,
) -> TaskDetail:
    analysis, bundle = analysis_material(session, project, analysis_id)
    row = _revision(session, project, analysis, feedback_revision_id)
    feedback = _feedback(session, project, analysis, bundle, row)
    by_id = {item["task"]["task_id"]: item for item in feedback.progress}
    if task_id not in by_id:
        deny("review_task_not_found", 404)
    item = by_id[task_id]
    authors = _authors(row)
    return TaskDetail(
        **_identity(analysis, bundle),
        feedback_revision_id=row.id,
        binding=feedback.submission["binding"],
        material=_material(item, feedback, authors),
        dependencies=[
            _material(by_id[key], feedback, authors)
            for key in item["task"]["depends_on"]
        ],
    )


def append_feedback(
    session: Session,
    project: Project,
    analysis_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    key: str,
    body: FeedbackPatch,
) -> FeedbackPublic:
    # project_for(write=True) owns the first lock; never reverse Project -> Analysis.
    locked = session.exec(
        select(NetFlowAnalysis)
        .where(
            NetFlowAnalysis.id == analysis_id,
            NetFlowAnalysis.project_id == project.id,
            NetFlowAnalysis.tenant_id == project.tenant_id,
        )
        .with_for_update()
    ).first()
    if locked is None:
        deny("netflow_analysis_not_found", 404)
    analysis, bundle = analysis_material(session, project, analysis_id)
    request = {"analysis_id": str(analysis_id), **body.model_dump(mode="json")}
    operation = f"feedback:{analysis_id}"
    recovered = operation_result(session, project, actor_id, operation, key, request)
    if recovered is not None:
        row = _revision(session, project, analysis, recovered)
        return feedback_public(
            analysis, bundle, row, _feedback(session, project, analysis, bundle, row)
        )
    context = context_for(
        session, project, analysis.dataset_id, analysis.context_revision_id
    )
    validate_context(session, project, context, write=True)
    _revision(session, project, analysis, body.expected_parent_id)
    parent = _revision(session, project, analysis, None)
    if parent.id != body.expected_parent_id:
        deny("netflow_revision_conflict")
    previous = _feedback(session, project, analysis, bundle, parent)
    result = processor.review_feedback_patch(
        bundle,
        previous,
        [item.model_dump(mode="json") for item in body.responses],
        output_dir=new_output_directory(project.id, "feedback"),
        allow_test=settings.NETFLOW_ALLOW_TEST_FIXTURES,
    )
    row = NetFlowFeedbackRevision(
        tenant_id=project.tenant_id,
        project_id=project.id,
        analysis_id=analysis.id,
        parent_id=parent.id,
        revision=parent.revision + 1,
        created_by=actor_id,
        human_note=body.human_note,
        created_at=get_datetime_utc(),
        artifact_manifest=seal_artifacts(session, project, result.root, result.files),
    )
    authors = _authors(parent)
    for item in body.responses:
        authors[item.task_id] = Author(
            actor_id=actor_id, submitted_at=row.created_at, feedback_revision_id=row.id
        )
    row.provider_claim = {
        "response_authors": {
            task: author.model_dump(mode="json") for task, author in authors.items()
        }
    }
    session.add(row)
    record_operation(session, project, actor_id, operation, key, request, row.id)
    public = feedback_public(
        analysis, bundle, row, _feedback(session, project, analysis, bundle, row)
    )
    session.commit()
    return public


def read_operation(
    session: Session,
    project: Project,
    analysis_id: uuid.UUID,
    actor_id: uuid.UUID,
    key: str,
) -> FeedbackPublic:
    analysis, bundle = analysis_material(session, project, analysis_id)
    revision_id = operation_result(
        session, project, actor_id, f"feedback:{analysis_id}", key
    )
    if revision_id is None:
        deny("review_task_not_found", 404)
    row = _revision(session, project, analysis, revision_id)
    return feedback_public(
        analysis, bundle, row, _feedback(session, project, analysis, bundle, row)
    )


def read_peers(
    session: Session,
    project: Project,
    analysis_id: uuid.UUID,
    *,
    ip: str | None,
    protocol: int | None,
    peer_port: int | None,
    sort: Literal["ip_asc", "ip_desc"],
    skip: int,
    limit: int,
) -> PeerPage:
    analysis, bundle = analysis_material(session, project, analysis_id)
    canonical = normalize_ip(ip) if ip is not None else None
    selected = [
        item
        for item in bundle.peers
        if (canonical is None or normalize_ip(item["ip"]) == canonical)
        and (protocol is None or item["protocol"] == protocol)
        and (peer_port is None or item["peer_port"] == peer_port)
    ]
    selected.sort(
        key=lambda item: (
            ipaddress.ip_address(normalize_ip(item["ip"])).version,
            int(ipaddress.ip_address(normalize_ip(item["ip"]))),
            item["peer_key"],
        ),
        reverse=sort == "ip_desc",
    )
    return PeerPage(
        **_identity(analysis, bundle),
        count=len(selected),
        skip=skip,
        limit=limit,
        total_peers=len(bundle.peers),
        total_peer_records=sum(item["record_count"] for item in bundle.peers),
        data=[
            Peer(
                peer_key=item["peer_key"],
                canonical_ip=normalize_ip(item["ip"]),
                family=ipaddress.ip_address(normalize_ip(item["ip"])).version,
                protocol_number=item["protocol"],
                peer_port=item["peer_port"],
                source_record_count=item["record_count"],
                retained_count=len(item["source_refs"]),
                omitted_count=item["source_refs_omitted"],
                original=item,
            )
            for item in selected[skip : skip + limit]
        ],
    )


def read_evidence(
    session: Session,
    project: Project,
    analysis_id: uuid.UUID,
    *,
    object_key: str | None,
    peer_key: str | None,
    skip: int,
    limit: int,
) -> EvidencePage:
    if (object_key is None) == (peer_key is None):
        deny("netflow_artifact_schema_invalid", 422)
    analysis, bundle = analysis_material(session, project, analysis_id)
    side: Literal["source", "peer"] = "source" if object_key is not None else "peer"
    key_name, key, rows = (
        ("object_key", object_key, bundle.observations)
        if side == "source"
        else ("peer_key", peer_key, bundle.peers)
    )
    item = next((row for row in rows if row[key_name] == key), None)
    if item is None:
        deny("netflow_input_not_found", 404)
    refs = item["source_refs"]
    artifact_name = "observations.jsonl" if side == "source" else "peers.jsonl"
    artifact = next(
        row for row in bundle.manifest["artifacts"] if row["path"] == artifact_name
    )
    return EvidencePage(
        **_identity(analysis, bundle),
        side=side,
        object_key=object_key,
        peer_key=peer_key,
        data=[
            EvidenceRef(
                reference=ref, side=side, object_key=object_key, peer_key=peer_key
            )
            for ref in refs[skip : skip + limit]
        ],
        count=len(refs),
        skip=skip,
        limit=limit,
        retained_count=len(refs),
        omitted_count=item["source_refs_omitted"],
        source_record_count=item["features"]["record_count"]
        if side == "source"
        else item["record_count"],
        input_sha256=bundle.manifest["input_sha256"],
        artifact_sha256=artifact["sha256"],
        component_binding={
            field: bundle.manifest[field]
            for field in (
                "tenant_id",
                "project_id",
                "dataset_id",
                "network_namespace",
                "run_id",
            )
        },
    )
