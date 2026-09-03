"""Immutable-input AI governance draft state machine and runner handoff."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session, col, select

from app.core.time import get_datetime_utc
from app.domain.evidence_selector import EvidenceBundle, EvidenceFactType
from app.domain.ip_consistency import IPRecordContractError, normalize_ip
from app.domain.models import (
    AiGovernanceDraft,
    AiGovernanceDraftFindingBinding,
    AiGovernanceDraftReviewDecision,
    AiGovernanceDraftStatus,
    AuditEvent,
    Evidence,
    Finding,
    GovernanceReport,
    GovernanceRun,
    GovernanceRunStatus,
    Project,
)

MAX_SELECTED_FINDINGS = 8
MAX_CLAIMS_PER_FINDING = 8
MAX_EVIDENCE_CITATIONS_PER_CLAIM = 1
MAX_TEXT_LIST_ENTRIES = 16
MAX_TEXT_LIST_ENTRY_LENGTH = 2000


def _nonblank_text(value: str) -> str:
    if not value.strip():
        raise ValueError("blank string")
    return value


NonBlankText = Annotated[str, AfterValidator(_nonblank_text)]
DraftIdentityText = Annotated[str, Field(min_length=36, max_length=36)]
DraftListText = Annotated[
    str,
    Field(min_length=1, max_length=MAX_TEXT_LIST_ENTRY_LENGTH),
    AfterValidator(_nonblank_text),
]


class AiGovernanceDraftStateError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class DraftFindingBinding:
    finding_id: uuid.UUID
    evidence_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class AiGovernanceDraftCreation:
    draft: AiGovernanceDraft
    created: bool


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _is_lower_hex_identity(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_failure_code(value: str) -> bool:
    return (
        1 <= len(value) <= 100
        and value[0] in "abcdefghijklmnopqrstuvwxyz"
        and all(
            character in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in value
        )
    )


def _require_nonblank(value: str, *, max_length: int, code: str) -> None:
    if not value.strip() or len(value) > max_length:
        raise AiGovernanceDraftStateError(code)


def report_identity_hash(report: GovernanceReport) -> str:
    return hashlib.sha256(_canonical_bytes(report.canonical_content)).hexdigest()


class AiDraftModelClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: NonBlankText = Field(min_length=1, max_length=100)
    evidence_ids: list[DraftIdentityText] = Field(
        min_length=1,
        max_length=MAX_EVIDENCE_CITATIONS_PER_CLAIM,
    )


class _AiDraftFindingText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: DraftIdentityText
    rescan_recommendation: NonBlankText = Field(min_length=1, max_length=4000)
    pending_verifications: list[DraftListText] = Field(
        default_factory=list, max_length=MAX_TEXT_LIST_ENTRIES
    )
    limitations: list[DraftListText] = Field(
        default_factory=list, max_length=MAX_TEXT_LIST_ENTRIES
    )


class AiDraftRecommendation(_AiDraftFindingText):
    claims: list[AiDraftModelClaim] = Field(
        min_length=1, max_length=MAX_CLAIMS_PER_FINDING
    )


class AiDraftModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: NonBlankText = Field(min_length=1, max_length=4000)
    recommendations: list[AiDraftRecommendation] = Field(
        min_length=1, max_length=MAX_SELECTED_FINDINGS
    )


class AiDraftEditedFinding(_AiDraftFindingText):
    pass


class AiDraftEditedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[AiDraftEditedFinding] = Field(
        min_length=1, max_length=MAX_SELECTED_FINDINGS
    )


class AiGovernanceDraftReviewRequest(BaseModel):
    """The deliberately narrow public contract for a terminal review."""

    model_config = ConfigDict(extra="forbid")

    decision: AiGovernanceDraftReviewDecision
    edited_output: AiDraftEditedOutput | None = None


@dataclass(frozen=True, slots=True)
class DraftRunnerEvidenceReference:
    id: uuid.UUID
    fact_type: EvidenceFactType
    fact_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class DraftRunnerFindingInput:
    finding_id: uuid.UUID
    finding_type: Literal["UNOBSERVED_ASSET"]
    canonical_ip: str
    coverage: Literal["CURRENT_RUN_TRANSITION", "OPEN_BACKLOG"]
    transition_type: Literal["OPENED", "REOPENED", "CLOSED"] | None
    evidence: tuple[DraftRunnerEvidenceReference, ...]


@dataclass(frozen=True, slots=True)
class DraftRunnerInputs:
    draft_id: uuid.UUID
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    governance_run_id: uuid.UUID
    governance_report_id: uuid.UUID
    report_sha256: str
    model_identity: str
    config_fingerprint: str
    findings: tuple[DraftRunnerFindingInput, ...]


@dataclass(frozen=True, slots=True)
class DraftRunnerHandoff:
    """Persisted draft and validated Session identity only."""

    draft_id: uuid.UUID
    agent_compose_run_id: str
    session_id: str

    @classmethod
    def from_environment(cls, environment: dict[str, str]) -> DraftRunnerHandoff:
        raw_draft_id = environment.get("AI_DRAFT_ID", "").strip()
        try:
            draft_id = uuid.UUID(raw_draft_id)
        except ValueError:
            raise AiGovernanceDraftStateError("runner_handoff_invalid") from None
        if str(draft_id) != raw_draft_id:
            raise AiGovernanceDraftStateError("runner_handoff_invalid")
        agent_compose_run_id = environment.get("AI_DRAFT_RUN_ID", "").strip()
        session_id = environment.get("SANDBOX_ID", "").strip()
        if not _is_lower_hex_identity(
            agent_compose_run_id
        ) or not _is_lower_hex_identity(session_id):
            raise AiGovernanceDraftStateError("runner_handoff_invalid")
        return cls(
            draft_id=draft_id,
            agent_compose_run_id=agent_compose_run_id,
            session_id=session_id,
        )


@dataclass(frozen=True, slots=True)
class _CanonicalEvidenceBinding:
    finding_id: uuid.UUID
    finding_type: Literal["UNREPORTED_ASSET", "UNOBSERVED_ASSET"]
    canonical_ip: str
    coverage: Literal["CURRENT_RUN_TRANSITION", "OPEN_BACKLOG"]
    transition_type: Literal["OPENED", "REOPENED", "CLOSED"] | None
    fact_type: EvidenceFactType
    fact_id: uuid.UUID


def _locked_active_project(
    *, session: Session, project_id: uuid.UUID, tenant_id: uuid.UUID
) -> Project:
    project = session.exec(
        select(Project)
        .where(Project.id == project_id, Project.tenant_id == tenant_id)
        .with_for_update()
    ).one_or_none()
    if project is None:
        raise AiGovernanceDraftStateError("draft_project_not_found")
    if project.archived_at is not None:
        raise AiGovernanceDraftStateError("draft_project_archived")
    return project


def _locked_active_draft(*, session: Session, draft_id: uuid.UUID) -> AiGovernanceDraft:
    scope = session.exec(
        select(AiGovernanceDraft.project_id, AiGovernanceDraft.tenant_id).where(
            AiGovernanceDraft.id == draft_id
        )
    ).one_or_none()
    if scope is None:
        raise AiGovernanceDraftStateError("draft_not_found")
    _locked_active_project(session=session, project_id=scope[0], tenant_id=scope[1])
    draft = session.exec(
        select(AiGovernanceDraft)
        .where(AiGovernanceDraft.id == draft_id)
        .with_for_update()
    ).one_or_none()
    if draft is None:
        raise AiGovernanceDraftStateError("draft_not_found")
    return draft


def _draft_audit_event(
    *,
    draft: AiGovernanceDraft,
    actor_subject: str,
    actor_type: Literal["system", "user"],
    action: str,
    before_data: dict[str, Any] | None,
    after_data: dict[str, Any],
) -> AuditEvent:
    """Build a bounded event from the persisted draft scope, never caller data."""
    return AuditEvent(
        tenant_id=draft.tenant_id,
        project_id=draft.project_id,
        actor_subject=actor_subject,
        actor_type=actor_type,
        action=action,
        target_type="ai_governance_draft",
        target_id=draft.id,
        before_data=before_data,
        after_data=after_data,
    )


def _require_generating(draft: AiGovernanceDraft) -> None:
    if draft.status != AiGovernanceDraftStatus.GENERATING.value:
        raise AiGovernanceDraftStateError("draft_not_generating")


def _require_compatible_persisted_session_identity(
    *,
    draft: AiGovernanceDraft,
    agent_compose_run_id: str | None = None,
    agent_compose_project_id: str | None = None,
    agent_compose_agent_name: str | None = None,
    session_id: str | None = None,
) -> None:
    if (
        agent_compose_run_id is not None
        and draft.agent_compose_run_id is not None
        and draft.agent_compose_run_id != agent_compose_run_id
    ) or (
        agent_compose_project_id is not None
        and draft.agent_compose_project_id is not None
        and draft.agent_compose_project_id != agent_compose_project_id
    ) or (
        agent_compose_agent_name is not None
        and draft.agent_compose_agent_name is not None
        and draft.agent_compose_agent_name != agent_compose_agent_name
    ) or (
        session_id is not None
        and draft.session_id is not None
        and draft.session_id != session_id
    ):
        raise AiGovernanceDraftStateError("session_already_bound")


def _require_agent_compose_namespace(
    *,
    agent_compose_run_id: str,
    agent_compose_project_id: str,
    agent_compose_agent_name: str,
) -> None:
    if (
        not _is_lower_hex_identity(agent_compose_run_id)
        or not _is_lower_hex_identity(agent_compose_project_id)
    ):
        raise AiGovernanceDraftStateError("session_identity_invalid")
    _require_nonblank(
        agent_compose_agent_name,
        max_length=255,
        code="session_identity_invalid",
    )


def draft_agent_compose_namespace(
    draft: AiGovernanceDraft,
) -> tuple[str, str] | None:
    """Return the immutable namespace for a reserved Run, fail closed if partial."""

    run_id = draft.agent_compose_run_id
    project_id = draft.agent_compose_project_id
    agent_name = draft.agent_compose_agent_name
    values = (run_id, project_id, agent_name)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise AiGovernanceDraftStateError("session_identity_invalid")
    assert isinstance(run_id, str)
    assert isinstance(project_id, str)
    assert isinstance(agent_name, str)
    _require_agent_compose_namespace(
        agent_compose_run_id=run_id,
        agent_compose_project_id=project_id,
        agent_compose_agent_name=agent_name,
    )
    return project_id, agent_name


def _is_same_run_failed_reconciliation(
    *, draft: AiGovernanceDraft, agent_compose_run_id: str
) -> bool:
    """Allow a stale completion only for the already-reserved failed Run."""

    return (
        draft.status == AiGovernanceDraftStatus.FAILED.value
        and draft.agent_compose_run_id == agent_compose_run_id
    )


def _require_input_sealed(draft: AiGovernanceDraft) -> None:
    if draft.bindings_sealed_at is None:
        raise AiGovernanceDraftStateError("draft_input_unsealed")


def _bound_selections(
    *, session: Session, draft: AiGovernanceDraft
) -> dict[uuid.UUID, uuid.UUID]:
    _require_input_sealed(draft)
    rows = session.exec(
        select(AiGovernanceDraftFindingBinding).where(
            AiGovernanceDraftFindingBinding.draft_id == draft.id
        )
    ).all()
    selections: dict[uuid.UUID, uuid.UUID] = {}
    for row in rows:
        if (
            row.governance_run_id != draft.governance_run_id
            or row.project_id != draft.project_id
            or row.tenant_id != draft.tenant_id
            or row.finding_id in selections
            or row.evidence_id in selections.values()
        ):
            raise AiGovernanceDraftStateError("draft_input_invalid")
        selections[row.finding_id] = row.evidence_id
    if not 1 <= len(selections) <= MAX_SELECTED_FINDINGS:
        raise AiGovernanceDraftStateError("draft_input_invalid")
    return selections


def _validated_bindings(
    *, bindings: Sequence[DraftFindingBinding]
) -> dict[uuid.UUID, uuid.UUID]:
    selections: dict[uuid.UUID, uuid.UUID] = {}
    for binding in bindings:
        if binding.finding_id in selections:
            raise AiGovernanceDraftStateError("invalid_bindings")
        selections[binding.finding_id] = binding.evidence_id
    if not 1 <= len(selections) <= MAX_SELECTED_FINDINGS:
        raise AiGovernanceDraftStateError("invalid_bindings")
    if len(set(selections.values())) != len(selections):
        raise AiGovernanceDraftStateError("invalid_bindings")
    return selections


def _existing_idempotent_draft(
    *,
    session: Session,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    idempotency_key: str,
) -> AiGovernanceDraft | None:
    return session.exec(
        select(AiGovernanceDraft).where(
            AiGovernanceDraft.tenant_id == tenant_id,
            AiGovernanceDraft.project_id == project_id,
            AiGovernanceDraft.idempotency_key == idempotency_key,
        )
    ).one_or_none()


def _active_report_draft(
    *,
    session: Session,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    report_id: uuid.UUID,
) -> AiGovernanceDraft | None:
    return session.exec(
        select(AiGovernanceDraft).where(
            AiGovernanceDraft.tenant_id == tenant_id,
            AiGovernanceDraft.project_id == project_id,
            AiGovernanceDraft.governance_report_id == report_id,
            AiGovernanceDraft.status == AiGovernanceDraftStatus.GENERATING.value,
        )
    ).one_or_none()


def _published_report(
    *,
    session: Session,
    report_id: uuid.UUID,
    project_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> GovernanceReport | None:
    return session.exec(
        select(GovernanceReport)
        .join(
            GovernanceRun,
            col(GovernanceRun.id) == col(GovernanceReport.governance_run_id),
        )
        .where(
            GovernanceReport.id == report_id,
            GovernanceReport.project_id == project_id,
            GovernanceReport.tenant_id == tenant_id,
            col(GovernanceRun.status).in_(
                (
                    GovernanceRunStatus.COMPLETED.value,
                    GovernanceRunStatus.COMPLETED_WITH_WARNINGS.value,
                )
            ),
            col(GovernanceRun.completed_at).is_not(None),
        )
    ).one_or_none()


def require_published_report_for_draft(
    *, session: Session, report: GovernanceReport
) -> GovernanceReport:
    scoped_report = _published_report(
        session=session,
        report_id=report.id,
        project_id=report.project_id,
        tenant_id=report.tenant_id,
    )
    if scoped_report is not None:
        return scoped_report
    report_exists = session.exec(
        select(GovernanceReport.id).where(
            GovernanceReport.id == report.id,
            GovernanceReport.project_id == report.project_id,
            GovernanceReport.tenant_id == report.tenant_id,
        )
    ).one_or_none()
    code = "report_not_found" if report_exists is None else "report_not_published"
    raise AiGovernanceDraftStateError(code)


def _canonical_evidence_bindings(
    report: GovernanceReport,
) -> dict[uuid.UUID, _CanonicalEvidenceBinding]:
    content = report.canonical_content
    try:
        report_content = content["report"]
        report_identity = report_content["report_identity"]
        evidence_plan = EvidenceBundle.model_validate(content["evidence_plan"])
        if (
            content["schema_version"] != report.report_contract_version
            or report_identity["governance_run_id"] != str(report.governance_run_id)
            or report_identity["project_id"] != str(report.project_id)
            or report_identity["report_contract_version"]
            != report.report_contract_version
            or report_identity["generation_mode"] != report.generation_mode
            or evidence_plan.governance_run_id != str(report.governance_run_id)
            or evidence_plan.report_contract_version != report.report_contract_version
            or len(evidence_plan.entries) > evidence_plan.max_entries
        ):
            raise ValueError
    except KeyError, TypeError, ValidationError, ValueError:
        raise AiGovernanceDraftStateError("report_evidence_plan_invalid") from None

    bindings: dict[uuid.UUID, _CanonicalEvidenceBinding] = {}
    fact_references: set[tuple[EvidenceFactType, uuid.UUID]] = set()
    for entry in evidence_plan.entries:
        try:
            finding_id = uuid.UUID(entry.finding_id)
            fact_id = uuid.UUID(entry.evidence_reference.fact_id)
            canonical_ip = normalize_ip(entry.canonical_ip)
        except IPRecordContractError, ValueError:
            raise AiGovernanceDraftStateError("report_evidence_plan_invalid") from None
        fact_reference = (entry.evidence_reference.fact_type, fact_id)
        if (
            str(finding_id) != entry.finding_id
            or str(fact_id) != entry.evidence_reference.fact_id
            or entry.evidence_reference.governance_run_id
            != str(report.governance_run_id)
            or canonical_ip != entry.canonical_ip
            or finding_id in bindings
            or fact_reference in fact_references
        ):
            raise AiGovernanceDraftStateError("report_evidence_plan_invalid")
        bindings[finding_id] = _CanonicalEvidenceBinding(
            finding_id=finding_id,
            finding_type=entry.finding_type,
            canonical_ip=entry.canonical_ip,
            coverage=entry.coverage,
            transition_type=entry.transition_type,
            fact_type=entry.evidence_reference.fact_type,
            fact_id=fact_id,
        )
        fact_references.add(fact_reference)
    return bindings


def _evidence_target(evidence: Evidence) -> tuple[EvidenceFactType, uuid.UUID]:
    targets: tuple[tuple[EvidenceFactType, uuid.UUID | None], ...] = (
        ("SOURCE_SNAPSHOT", evidence.source_snapshot_id),
        ("OBSERVATION", evidence.observation_id),
        ("FINDING_OCCURRENCE", evidence.finding_occurrence_id),
        ("FINDING_TRANSITION", evidence.finding_transition_id),
    )
    present: list[tuple[EvidenceFactType, uuid.UUID]] = [
        (fact_type, fact_id) for fact_type, fact_id in targets if fact_id is not None
    ]
    if len(present) != 1:
        raise AiGovernanceDraftStateError("evidence_not_bound")
    fact_type, fact_id = present[0]
    return fact_type, fact_id


def _selected_facts(
    *,
    session: Session,
    report: GovernanceReport,
    selections: dict[uuid.UUID, uuid.UUID],
    finding_error: str,
    evidence_error: str,
) -> tuple[
    dict[uuid.UUID, _CanonicalEvidenceBinding],
    dict[uuid.UUID, Evidence],
]:
    canonical = _canonical_evidence_bindings(report)
    if not set(selections).issubset(canonical):
        raise AiGovernanceDraftStateError(finding_error)
    finding_ids = set(
        session.exec(
            select(Finding.id).where(
                col(Finding.id).in_(selections),
                Finding.project_id == report.project_id,
                Finding.tenant_id == report.tenant_id,
                Finding.finding_type == "UNOBSERVED_ASSET",
            )
        ).all()
    )
    if finding_ids != set(selections) or any(
        canonical[finding_id].finding_type != "UNOBSERVED_ASSET"
        for finding_id in finding_ids
    ):
        raise AiGovernanceDraftStateError(finding_error)
    evidence = session.exec(
        select(Evidence).where(
            col(Evidence.id).in_(selections.values()),
            Evidence.governance_report_id == report.id,
            Evidence.governance_run_id == report.governance_run_id,
            Evidence.project_id == report.project_id,
            Evidence.tenant_id == report.tenant_id,
        )
    ).all()
    evidence_by_id = {item.id: item for item in evidence}
    if set(evidence_by_id) != set(selections.values()) or any(
        _evidence_target(evidence_by_id[evidence_id])
        != (canonical[finding_id].fact_type, canonical[finding_id].fact_id)
        for finding_id, evidence_id in selections.items()
    ):
        raise AiGovernanceDraftStateError(evidence_error)
    return canonical, evidence_by_id


def draft_finding_bindings_for_request(
    *,
    session: Session,
    report: GovernanceReport,
    finding_ids: Sequence[uuid.UUID],
) -> tuple[DraftFindingBinding, ...]:
    """Resolve request IDs through the report's canonical Evidence plan.

    The public request deliberately carries Finding IDs only.  Evidence IDs are
    selected server-side from the persisted report scope, so a client cannot
    substitute a conveniently ordered or cross-report Evidence record.
    """
    unique_finding_ids = set(finding_ids)
    if len(unique_finding_ids) != len(finding_ids) or not (
        1 <= len(unique_finding_ids) <= MAX_SELECTED_FINDINGS
    ):
        raise AiGovernanceDraftStateError("invalid_bindings")

    canonical = _canonical_evidence_bindings(report)
    if not unique_finding_ids.issubset(canonical):
        raise AiGovernanceDraftStateError("finding_not_selected")
    required_targets = {
        (canonical[finding_id].fact_type, canonical[finding_id].fact_id)
        for finding_id in unique_finding_ids
    }
    scoped_evidence = session.exec(
        select(Evidence).where(
            Evidence.governance_report_id == report.id,
            Evidence.governance_run_id == report.governance_run_id,
            Evidence.project_id == report.project_id,
            Evidence.tenant_id == report.tenant_id,
        )
    ).all()
    evidence_by_target: dict[tuple[EvidenceFactType, uuid.UUID], uuid.UUID] = {}
    for evidence in scoped_evidence:
        target = _evidence_target(evidence)
        if target not in required_targets:
            continue
        if target in evidence_by_target:
            raise AiGovernanceDraftStateError("evidence_not_bound")
        evidence_by_target[target] = evidence.id
    if set(evidence_by_target) != required_targets:
        raise AiGovernanceDraftStateError("evidence_not_bound")

    bindings = tuple(
        DraftFindingBinding(
            finding_id=finding_id,
            evidence_id=evidence_by_target[
                (canonical[finding_id].fact_type, canonical[finding_id].fact_id)
            ],
        )
        for finding_id in sorted(unique_finding_ids)
    )
    selections = _validated_bindings(bindings=bindings)
    _selected_facts(
        session=session,
        report=report,
        selections=selections,
        finding_error="finding_not_selected",
        evidence_error="evidence_not_bound",
    )
    return bindings


def create_ai_governance_draft(
    *,
    session: Session,
    report: GovernanceReport,
    initiated_by: str,
    idempotency_key: str,
    model_identity: str,
    config_fingerprint: str,
    bindings: Sequence[DraftFindingBinding],
) -> AiGovernanceDraftCreation:
    _require_nonblank(initiated_by, max_length=255, code="draft_request_invalid")
    _require_nonblank(idempotency_key, max_length=255, code="draft_request_invalid")
    _require_nonblank(model_identity, max_length=255, code="draft_request_invalid")
    if not _is_lower_hex_identity(config_fingerprint):
        raise AiGovernanceDraftStateError("draft_request_invalid")
    scoped_report = require_published_report_for_draft(session=session, report=report)

    tenant_id = scoped_report.tenant_id
    project_id = scoped_report.project_id
    _locked_active_project(session=session, project_id=project_id, tenant_id=tenant_id)
    existing = _existing_idempotent_draft(
        session=session,
        tenant_id=tenant_id,
        project_id=project_id,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        if existing.governance_report_id != scoped_report.id:
            raise AiGovernanceDraftStateError("draft_idempotency_conflict")
        return AiGovernanceDraftCreation(draft=existing, created=False)
    if (
        _active_report_draft(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            report_id=scoped_report.id,
        )
        is not None
    ):
        raise AiGovernanceDraftStateError("draft_generation_active")

    selections = _validated_bindings(bindings=bindings)
    _selected_facts(
        session=session,
        report=scoped_report,
        selections=selections,
        finding_error="finding_not_selected",
        evidence_error="evidence_not_bound",
    )

    draft = AiGovernanceDraft(
        tenant_id=scoped_report.tenant_id,
        project_id=scoped_report.project_id,
        governance_run_id=scoped_report.governance_run_id,
        governance_report_id=scoped_report.id,
        report_sha256=report_identity_hash(scoped_report),
        initiated_by=initiated_by,
        idempotency_key=idempotency_key,
        model_identity=model_identity,
        config_fingerprint=config_fingerprint,
        status=AiGovernanceDraftStatus.GENERATING.value,
    )
    session.add(draft)
    try:
        session.flush()
    except IntegrityError as error:
        session.rollback()
        _locked_active_project(
            session=session, project_id=project_id, tenant_id=tenant_id
        )
        replay = _existing_idempotent_draft(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            if replay.governance_report_id != scoped_report.id:
                raise AiGovernanceDraftStateError("draft_idempotency_conflict")
            return AiGovernanceDraftCreation(draft=replay, created=False)
        if (
            _active_report_draft(
                session=session,
                tenant_id=tenant_id,
                project_id=project_id,
                report_id=scoped_report.id,
            )
            is not None
        ):
            raise AiGovernanceDraftStateError("draft_generation_active") from None
        raise error
    for finding_id in sorted(selections):
        session.add(
            AiGovernanceDraftFindingBinding(
                tenant_id=draft.tenant_id,
                project_id=draft.project_id,
                governance_run_id=draft.governance_run_id,
                draft_id=draft.id,
                finding_id=finding_id,
                evidence_id=selections[finding_id],
            )
        )
    try:
        session.flush()
        draft.bindings_sealed_at = get_datetime_utc()
        session.add(draft)
        session.flush()
        session.add(
            _draft_audit_event(
                draft=draft,
                actor_subject=draft.initiated_by,
                actor_type="user",
                action="ai_governance_draft.generation_requested",
                before_data=None,
                after_data={
                    "governance_report_id": str(draft.governance_report_id),
                    "status": draft.status,
                    "finding_count": len(selections),
                },
            )
        )
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(draft)
    return AiGovernanceDraftCreation(draft=draft, created=True)


def reserve_draft_run_identity(
    *,
    session: Session,
    draft: AiGovernanceDraft,
    agent_compose_run_id: str,
    agent_compose_project_id: str,
    agent_compose_agent_name: str,
) -> AiGovernanceDraft:
    """Durably reserve the deterministic Run before asking agent-compose to start it."""

    _require_agent_compose_namespace(
        agent_compose_run_id=agent_compose_run_id,
        agent_compose_project_id=agent_compose_project_id,
        agent_compose_agent_name=agent_compose_agent_name,
    )
    try:
        locked = _locked_active_draft(session=session, draft_id=draft.id)
        _require_compatible_persisted_session_identity(
            draft=locked,
            agent_compose_run_id=agent_compose_run_id,
            agent_compose_project_id=agent_compose_project_id,
            agent_compose_agent_name=agent_compose_agent_name,
        )
        if _is_same_run_failed_reconciliation(
            draft=locked, agent_compose_run_id=agent_compose_run_id
        ):
            session.commit()
            session.refresh(locked)
            return locked
        _require_generating(locked)
        _require_input_sealed(locked)
        if locked.agent_compose_run_id is not None:
            draft_agent_compose_namespace(locked)
            session.commit()
            session.refresh(locked)
            return locked
        if locked.session_id is not None:
            raise AiGovernanceDraftStateError("session_already_bound")
        reused_draft_identity = session.exec(
            select(AiGovernanceDraft.id).where(
                col(AiGovernanceDraft.agent_compose_run_id) == agent_compose_run_id,
                AiGovernanceDraft.id != locked.id,
            )
        ).first()
        if reused_draft_identity is not None:
            raise AiGovernanceDraftStateError("session_identity_reused")
        locked.agent_compose_run_id = agent_compose_run_id
        locked.agent_compose_project_id = agent_compose_project_id
        locked.agent_compose_agent_name = agent_compose_agent_name
        locked.updated_at = get_datetime_utc()
        try:
            return _commit_draft(session=session, draft=locked)
        except IntegrityError as error:
            diagnostic = getattr(error.orig, "diag", None)
            if (
                getattr(diagnostic, "constraint_name", None)
                == "uq_ai_governance_drafts_agent_compose_run"
            ):
                raise AiGovernanceDraftStateError("session_identity_reused") from None
            raise error
    except AiGovernanceDraftStateError:
        session.rollback()
        raise


def lock_draft_for_session_reconciliation(
    *,
    session: Session,
    draft: AiGovernanceDraft,
    agent_compose_run_id: str,
) -> AiGovernanceDraft:
    """Return an authoritative, detached draft snapshot for control-plane work.

    The row lock is only used to make this re-read authoritative.  A caller can
    safely consult agent-compose after this function returns: external control
    plane code (including a callback which records the Session) must never wait
    for this request's Project or draft lock.
    """

    if not _is_lower_hex_identity(agent_compose_run_id):
        raise AiGovernanceDraftStateError("session_identity_invalid")
    try:
        locked = _locked_active_draft(session=session, draft_id=draft.id)
        _require_compatible_persisted_session_identity(
            draft=locked,
            agent_compose_run_id=agent_compose_run_id,
        )
        draft_agent_compose_namespace(locked)
        if locked.status == AiGovernanceDraftStatus.GENERATING.value:
            _require_input_sealed(locked)
        # Keep the values needed by the control-plane decision, but close the
        # transaction before returning.  Expunging before commit preserves the
        # loaded snapshot while ensuring it cannot accidentally retain or
        # reopen this Session's lock-bearing transaction.
        session.expunge(locked)
        session.commit()
        return locked
    except AiGovernanceDraftStateError:
        session.rollback()
        raise
    except SQLAlchemyError:
        session.rollback()
        raise


def bind_draft_session(
    *,
    session: Session,
    draft: AiGovernanceDraft,
    agent_compose_run_id: str,
    session_id: str,
) -> AiGovernanceDraft:
    if not _is_lower_hex_identity(agent_compose_run_id) or not _is_lower_hex_identity(
        session_id
    ):
        raise AiGovernanceDraftStateError("session_identity_invalid")
    try:
        locked = _locked_active_draft(session=session, draft_id=draft.id)
        _require_compatible_persisted_session_identity(
            draft=locked,
            agent_compose_run_id=agent_compose_run_id,
            session_id=session_id,
        )
        if _is_same_run_failed_reconciliation(
            draft=locked, agent_compose_run_id=agent_compose_run_id
        ):
            session.commit()
            session.refresh(locked)
            return locked
        _require_generating(locked)
        _require_input_sealed(locked)
        if locked.session_id is not None:
            session.commit()
            session.refresh(locked)
            return locked
        reused_session = session.exec(
            select(GovernanceRun.id).where(GovernanceRun.session_id == session_id)
        ).one_or_none()
        if reused_session is not None:
            raise AiGovernanceDraftStateError("session_identity_reused")
        reused_draft_identity = session.exec(
            select(AiGovernanceDraft.id).where(
                or_(
                    col(AiGovernanceDraft.agent_compose_run_id) == agent_compose_run_id,
                    col(AiGovernanceDraft.session_id) == session_id,
                ),
                AiGovernanceDraft.id != locked.id,
            )
        ).first()
        if reused_draft_identity is not None:
            raise AiGovernanceDraftStateError("session_identity_reused")
        locked.agent_compose_run_id = agent_compose_run_id
        locked.session_id = session_id
        locked.updated_at = get_datetime_utc()
        try:
            return _commit_draft(session=session, draft=locked)
        except IntegrityError as error:
            diagnostic = getattr(error.orig, "diag", None)
            if getattr(diagnostic, "constraint_name", None) in {
                "uq_ai_governance_drafts_agent_compose_run",
                "uq_ai_governance_drafts_session",
            }:
                raise AiGovernanceDraftStateError("session_identity_reused") from None
            raise error
    except AiGovernanceDraftStateError:
        session.rollback()
        raise


def mark_draft_reviewable(
    *,
    session: Session,
    draft: AiGovernanceDraft,
    model_output: AiDraftModelOutput,
) -> AiGovernanceDraft:
    try:
        locked = _locked_active_draft(session=session, draft_id=draft.id)
        _require_generating(locked)
        _require_input_sealed(locked)
        if locked.session_id is None:
            raise AiGovernanceDraftStateError("session_not_bound")
        selections = _bound_selections(session=session, draft=locked)
        validated_output = _validate_model_output(
            model_output=model_output,
            report_sha256=locked.report_sha256,
            selections=selections,
        )
        locked.status = AiGovernanceDraftStatus.REVIEWABLE.value
        locked.model_output = validated_output
        locked.generation_terminal_at = get_datetime_utc()
        locked.updated_at = get_datetime_utc()
        return _commit_transition(
            session=session,
            draft=locked,
            audit_event=_draft_audit_event(
                draft=locked,
                actor_subject="ai-draft-runner",
                actor_type="system",
                action="ai_governance_draft.generation_succeeded",
                before_data={"status": AiGovernanceDraftStatus.GENERATING.value},
                after_data={"status": locked.status},
            ),
        )
    except AiGovernanceDraftStateError:
        session.rollback()
        raise


def fail_draft(
    *,
    session: Session,
    draft: AiGovernanceDraft,
    failure_code: str,
    actor_subject: str = "ai-draft-runner",
    agent_compose_run_id: str | None = None,
    session_id: str | None = None,
) -> AiGovernanceDraft:
    if not _is_failure_code(failure_code):
        raise AiGovernanceDraftStateError("failure_code_invalid")
    _require_nonblank(actor_subject, max_length=255, code="draft_request_invalid")
    if (agent_compose_run_id is None) != (session_id is None):
        raise AiGovernanceDraftStateError("session_identity_invalid")
    if agent_compose_run_id is not None and (
        not _is_lower_hex_identity(agent_compose_run_id)
        or not _is_lower_hex_identity(session_id)
    ):
        raise AiGovernanceDraftStateError("session_identity_invalid")
    try:
        locked = _locked_active_draft(session=session, draft_id=draft.id)
        _require_compatible_persisted_session_identity(
            draft=locked,
            agent_compose_run_id=agent_compose_run_id,
            session_id=session_id,
        )
        if agent_compose_run_id is not None and _is_same_run_failed_reconciliation(
            draft=locked, agent_compose_run_id=agent_compose_run_id
        ):
            session.commit()
            session.refresh(locked)
            return locked
        _require_generating(locked)
        _require_input_sealed(locked)
        if agent_compose_run_id is not None and session_id is not None:
            reused_session = session.exec(
                select(GovernanceRun.id).where(GovernanceRun.session_id == session_id)
            ).one_or_none()
            if reused_session is not None:
                raise AiGovernanceDraftStateError("session_identity_reused")
            reused_draft_identity = session.exec(
                select(AiGovernanceDraft.id).where(
                    or_(
                        col(AiGovernanceDraft.agent_compose_run_id)
                        == agent_compose_run_id,
                        col(AiGovernanceDraft.session_id) == session_id,
                    ),
                    AiGovernanceDraft.id != locked.id,
                )
            ).first()
            if reused_draft_identity is not None:
                raise AiGovernanceDraftStateError("session_identity_reused")
            locked.agent_compose_run_id = agent_compose_run_id
            locked.session_id = session_id
        locked.status = AiGovernanceDraftStatus.FAILED.value
        locked.failure_code = failure_code
        locked.generation_terminal_at = get_datetime_utc()
        locked.updated_at = get_datetime_utc()
        return _commit_transition(
            session=session,
            draft=locked,
            audit_event=_draft_audit_event(
                draft=locked,
                actor_subject=actor_subject,
                actor_type="system",
                action="ai_governance_draft.generation_failed",
                before_data={"status": AiGovernanceDraftStatus.GENERATING.value},
                after_data={"status": locked.status, "failure_code": failure_code},
            ),
        )
    except AiGovernanceDraftStateError:
        session.rollback()
        raise


def review_draft(
    *,
    session: Session,
    draft: AiGovernanceDraft,
    reviewer: str,
    decision: AiGovernanceDraftReviewDecision,
    edited_output: AiDraftEditedOutput | None = None,
) -> AiGovernanceDraft:
    _require_nonblank(reviewer, max_length=255, code="reviewer_invalid")
    try:
        normalized_decision = AiGovernanceDraftReviewDecision(decision)
    except TypeError, ValueError:
        raise AiGovernanceDraftStateError("invalid_review_decision") from None
    try:
        locked = _locked_active_draft(session=session, draft_id=draft.id)
        _require_input_sealed(locked)
        if locked.status != AiGovernanceDraftStatus.REVIEWABLE.value:
            raise AiGovernanceDraftStateError("draft_not_reviewable")
        if locked.review_decision is not None:
            raise AiGovernanceDraftStateError("draft_already_reviewed")
        selections = _bound_selections(session=session, draft=locked)
        try:
            persisted_model_output = AiDraftModelOutput.model_validate(
                locked.model_output
            )
        except (TypeError, ValidationError):
            raise AiGovernanceDraftStateError("draft_model_output_invalid") from None
        _validate_model_output(
            model_output=persisted_model_output,
            report_sha256=locked.report_sha256,
            selections=selections,
        )
        validated_edited_output: dict[str, Any] | None = None
        if normalized_decision == AiGovernanceDraftReviewDecision.EDITED:
            if edited_output is None:
                raise AiGovernanceDraftStateError("review_requires_edited_output")
            validated_edited_output = _validate_edited_output(
                edited_output=edited_output,
                selections=selections,
            )
        elif edited_output is not None:
            raise AiGovernanceDraftStateError("invalid_review_decision")
        locked.review_decision = normalized_decision.value
        locked.reviewed_by = reviewer
        locked.reviewed_at = get_datetime_utc()
        locked.operator_edited_output = validated_edited_output
        locked.updated_at = get_datetime_utc()
        return _commit_transition(
            session=session,
            draft=locked,
            audit_event=_draft_audit_event(
                draft=locked,
                actor_subject=reviewer,
                actor_type="user",
                action="ai_governance_draft.reviewed",
                before_data={"review_decision": None},
                after_data={"review_decision": normalized_decision.value},
            ),
        )
    except AiGovernanceDraftStateError:
        session.rollback()
        raise


def _commit_transition(
    *,
    session: Session,
    draft: AiGovernanceDraft,
    audit_event: AuditEvent,
) -> AiGovernanceDraft:
    session.add(audit_event)
    return _commit_draft(session=session, draft=draft)


def _commit_draft(*, session: Session, draft: AiGovernanceDraft) -> AiGovernanceDraft:
    try:
        session.add(draft)
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(draft)
    return draft


def _validate_model_output(
    *,
    model_output: AiDraftModelOutput,
    report_sha256: str,
    selections: dict[uuid.UUID, uuid.UUID],
) -> dict[str, Any]:
    try:
        _validate_model_output_semantics(
            model_output=model_output,
            report_sha256=report_sha256,
            selections=selections,
        )
    except AttributeError, TypeError:
        raise AiGovernanceDraftStateError("model_output_invalid") from None
    return _validated_payload(model_output, AiDraftModelOutput, "model_output_invalid")


def _validate_model_output_semantics(
    *,
    model_output: AiDraftModelOutput,
    report_sha256: str,
    selections: dict[uuid.UUID, uuid.UUID],
) -> None:
    if model_output.report_sha256 != report_sha256:
        raise AiGovernanceDraftStateError("model_output_report_mismatch")
    covered: set[uuid.UUID] = set()
    for recommendation in model_output.recommendations:
        try:
            finding_id = uuid.UUID(recommendation.finding_id)
        except ValueError:
            raise AiGovernanceDraftStateError("model_output_finding_unknown") from None
        if (
            str(finding_id) != recommendation.finding_id
            or finding_id not in selections
            or finding_id in covered
        ):
            raise AiGovernanceDraftStateError("model_output_finding_unknown")
        covered.add(finding_id)
        allowed_evidence = selections[finding_id]
        claim_ids: set[str] = set()
        cited_evidence: set[uuid.UUID] = set()
        for claim in recommendation.claims:
            if claim.claim_id in claim_ids:
                raise AiGovernanceDraftStateError("model_output_claim_duplicate")
            claim_ids.add(claim.claim_id)
            if len(set(claim.evidence_ids)) != len(claim.evidence_ids):
                raise AiGovernanceDraftStateError("model_output_evidence_duplicate")
            for evidence_id in claim.evidence_ids:
                try:
                    parsed = uuid.UUID(evidence_id)
                except ValueError:
                    raise AiGovernanceDraftStateError(
                        "model_output_evidence_out_of_bounds"
                    ) from None
                if str(parsed) != evidence_id or parsed != allowed_evidence:
                    raise AiGovernanceDraftStateError(
                        "model_output_evidence_out_of_bounds"
                    )
                cited_evidence.add(parsed)
        if cited_evidence != {allowed_evidence}:
            raise AiGovernanceDraftStateError("model_output_evidence_missing")
    if covered != set(selections):
        raise AiGovernanceDraftStateError("model_output_finding_missing")


def _validate_edited_output(
    *,
    edited_output: AiDraftEditedOutput,
    selections: dict[uuid.UUID, uuid.UUID],
) -> dict[str, Any]:
    try:
        _validate_edited_output_semantics(
            edited_output=edited_output,
            selections=selections,
        )
    except AttributeError, TypeError:
        raise AiGovernanceDraftStateError("edited_output_invalid") from None
    return _validated_payload(
        edited_output, AiDraftEditedOutput, "edited_output_invalid"
    )


def _validated_payload[ModelT: BaseModel](
    value: ModelT, schema: type[ModelT], error_code: str
) -> dict[str, Any]:
    try:
        validated = schema.model_validate(value.model_dump(warnings=False))
        return validated.model_dump()
    except AttributeError, TypeError, ValueError:
        raise AiGovernanceDraftStateError(error_code) from None


def _validate_edited_output_semantics(
    *,
    edited_output: AiDraftEditedOutput,
    selections: dict[uuid.UUID, uuid.UUID],
) -> None:
    covered: set[uuid.UUID] = set()
    for finding in edited_output.findings:
        try:
            finding_id = uuid.UUID(finding.finding_id)
        except ValueError:
            raise AiGovernanceDraftStateError("edited_output_finding_unknown") from None
        if (
            str(finding_id) != finding.finding_id
            or finding_id not in selections
            or finding_id in covered
        ):
            raise AiGovernanceDraftStateError("edited_output_finding_unknown")
        covered.add(finding_id)
    if covered != set(selections):
        raise AiGovernanceDraftStateError("edited_output_finding_missing")


def _evidence_reference(evidence: Evidence) -> DraftRunnerEvidenceReference:
    fact_type, fact_id = _evidence_target(evidence)
    return DraftRunnerEvidenceReference(
        id=evidence.id,
        fact_type=fact_type,
        fact_id=fact_id,
    )


def load_draft_runner_inputs(
    *,
    session: Session,
    draft_id: uuid.UUID,
    session_id: str,
) -> DraftRunnerInputs:
    draft = _locked_active_draft(session=session, draft_id=draft_id)
    if draft.session_id is None or draft.session_id != session_id:
        raise AiGovernanceDraftStateError("session_mismatch")
    _require_generating(draft)
    _require_input_sealed(draft)
    report = _published_report(
        session=session,
        report_id=draft.governance_report_id,
        project_id=draft.project_id,
        tenant_id=draft.tenant_id,
    )
    if (
        report is None
        or report.governance_run_id != draft.governance_run_id
        or report_identity_hash(report) != draft.report_sha256
    ):
        raise AiGovernanceDraftStateError("runner_input_changed")
    try:
        selections = _bound_selections(session=session, draft=draft)
    except AiGovernanceDraftStateError:
        raise AiGovernanceDraftStateError("runner_input_invalid") from None
    canonical, evidence = _selected_facts(
        session=session,
        report=report,
        selections=selections,
        finding_error="runner_input_invalid",
        evidence_error="runner_input_invalid",
    )
    return DraftRunnerInputs(
        draft_id=draft.id,
        tenant_id=draft.tenant_id,
        project_id=draft.project_id,
        governance_run_id=draft.governance_run_id,
        governance_report_id=draft.governance_report_id,
        report_sha256=draft.report_sha256,
        model_identity=draft.model_identity,
        config_fingerprint=draft.config_fingerprint,
        findings=tuple(
            DraftRunnerFindingInput(
                finding_id=finding_id,
                finding_type="UNOBSERVED_ASSET",
                canonical_ip=canonical[finding_id].canonical_ip,
                coverage=canonical[finding_id].coverage,
                transition_type=canonical[finding_id].transition_type,
                evidence=(_evidence_reference(evidence[evidence_id]),),
            )
            for finding_id, evidence_id in sorted(selections.items())
        ),
    )
