"""Transaction-local comparison binding and immutable published report resolution.

The caller owns publication. Binding is deliberately before activity/lifecycle
writes; resolution is deliberately after publication, with no Artifact file I/O.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlmodel import Session, col, select

from app.domain.comparison_evidence import (
    ComparisonEvidenceReference,
    comparison_evidence_id,
)
from app.domain.ip_source_comparison import (
    COMPARISON_CONTRACT_VERSION,
    IPSourceComparison,
    IPSourceComparisonError,
    RunIPSourceComparison,
    comparison_fact_id,
)
from app.domain.models import (
    Artifact,
    AuditEvent,
    Evidence,
    Finding,
    FindingOccurrence,
    FindingOccurrenceObservation,
    FindingOccurrenceSnapshot,
    FindingTransition,
    FindingTransitionObservation,
    FindingTransitionSnapshot,
    GovernanceReport,
    GovernanceRun,
    IPSourceComparisonFact,
    NetFlowIPActivity,
    Observation,
    RunStep,
    SourceSnapshot,
)
from app.domain.report_candidate_facts import read_report_candidate_facts
from app.domain.report_candidates import (
    REPORT_V2_CONTRACT_VERSION,
    CanonicalReportV2,
    FrozenReportCandidateFacts,
    ReportCandidate,
    ReportCandidateError,
    generate_report_candidate,
    validate_report_candidate,
)


class ReportComparisonEvidenceError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ReportComparisonEvidenceBinding:
    evidence_id: uuid.UUID
    evidence_reference: ComparisonEvidenceReference
    fact: IPSourceComparison


def _require(condition: bool, code: str = "comparison_evidence_invalid") -> None:
    if not condition:
        raise ReportComparisonEvidenceError(code)


def _canonical_bytes(content: dict[str, Any]) -> bytes:
    return json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _scoped_report(
    *,
    session: Session,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    report_id: uuid.UUID,
) -> tuple[GovernanceReport, GovernanceRun]:
    report = session.exec(
        select(GovernanceReport).where(
            GovernanceReport.id == report_id,
            GovernanceReport.tenant_id == tenant_id,
            GovernanceReport.project_id == project_id,
        )
    ).one_or_none()
    _require(report is not None, "report_not_found")
    assert report is not None
    run = session.exec(
        select(GovernanceRun).where(
            GovernanceRun.id == report.governance_run_id,
            GovernanceRun.tenant_id == tenant_id,
            GovernanceRun.project_id == project_id,
        )
    ).one_or_none()
    _require(run is not None)
    assert run is not None
    _require(
        report.report_contract_version == REPORT_V2_CONTRACT_VERSION
        and run.report_contract_version == REPORT_V2_CONTRACT_VERSION,
        "report_contract_unsupported",
    )
    return report, run


def _require_binding_stage(*, session: Session, run: GovernanceRun) -> None:
    _require(run.status == "RUNNING" and run.completed_at is None, "report_not_ready")
    for item in (*session.new, *session.dirty, *session.deleted):
        if isinstance(item, Finding):
            relevant = (
                item.tenant_id == run.tenant_id and item.project_id == run.project_id
            )
        else:
            relevant = getattr(item, "governance_run_id", None) == run.id
        if not relevant:
            continue
        if isinstance(
            item,
            (
                Finding,
                FindingOccurrence,
                FindingTransition,
                NetFlowIPActivity,
                FindingOccurrenceObservation,
                FindingOccurrenceSnapshot,
                FindingTransitionObservation,
                FindingTransitionSnapshot,
            ),
        ):
            raise ReportComparisonEvidenceError("report_not_ready")
        if isinstance(item, Evidence) and (
            item.finding_occurrence_id is not None
            or item.finding_transition_id is not None
        ):
            raise ReportComparisonEvidenceError("report_not_ready")
        # Flushes below must never silently publish caller's pending mutations.
        _require(False)
    for model in (NetFlowIPActivity, FindingOccurrence, FindingTransition):
        _require(
            session.exec(
                select(model.id).where(model.governance_run_id == run.id).limit(1)
            ).first()
            is None,
            "report_not_ready",
        )
    _require(
        session.exec(
            select(Evidence.id)
            .where(
                Evidence.governance_run_id == run.id,
                (col(Evidence.finding_occurrence_id).is_not(None))
                | (col(Evidence.finding_transition_id).is_not(None)),
            )
            .limit(1)
        ).first()
        is None,
        "report_not_ready",
    )


def _report_matches_candidate(
    *,
    session: Session,
    report: GovernanceReport,
    candidate: ReportCandidate,
) -> CanonicalReportV2:
    content = report.canonical_content.get("report")
    if isinstance(content, dict):
        comparison = content.get("ip_source_comparison")
        if isinstance(comparison, dict) and isinstance(
            comparison.get("contract_version"), str
        ):
            _require(
                comparison["contract_version"] == COMPARISON_CONTRACT_VERSION,
                "comparison_contract_unsupported",
            )
    canonical = CanonicalReportV2.model_validate(report.canonical_content)
    identity = canonical.report.report_identity
    _require(
        identity.project_id == str(report.project_id)
        and identity.governance_run_id == str(report.governance_run_id)
        and identity.generation_mode == report.generation_mode
        and canonical.report.ip_source_comparison.tenant_id == report.tenant_id
    )
    encoded = _canonical_bytes(report.canonical_content)
    rendered = candidate.rendered
    _require(
        encoded == rendered.canonical_json
        and hashlib.sha256(encoded).hexdigest() == rendered.canonical_json_sha256
        and report.html_sha256 == rendered.html_sha256
        and report.csv_sha256 == rendered.csv_sha256
    )
    for artifact_id, digest, body, media_type in (
        (report.html_artifact_id, rendered.html_sha256, rendered.html, "text/html"),
        (report.csv_artifact_id, rendered.csv_sha256, rendered.csv, "text/csv"),
    ):
        artifact = session.exec(
            select(Artifact)
            .where(
                Artifact.id == artifact_id,
                Artifact.tenant_id == report.tenant_id,
                Artifact.project_id == report.project_id,
                Artifact.governance_run_id == report.governance_run_id,
            )
            .execution_options(populate_existing=True)
        ).one_or_none()
        _require(
            artifact is not None
            and artifact.sha256 == digest
            and artifact.byte_size == len(body)
            and artifact.media_type == media_type
        )
    return canonical


def _fact_values(
    comparison: RunIPSourceComparison, row: IPSourceComparison
) -> dict[str, Any]:
    return {
        "id": comparison_fact_id(comparison.governance_run_id, row.canonical_ip),
        "tenant_id": comparison.tenant_id,
        "project_id": comparison.project_id,
        "governance_run_id": comparison.governance_run_id,
        "contract_version": COMPARISON_CONTRACT_VERSION,
        **row.model_dump(),
    }


def _comparison_records(
    *,
    session: Session,
    report: GovernanceReport,
) -> tuple[list[IPSourceComparisonFact], list[Evidence]]:
    # Query by ownership, not by the expected IDs: extra rows must be detected.
    facts = list(
        session.exec(
            select(IPSourceComparisonFact)
            .where(
                IPSourceComparisonFact.governance_run_id == report.governance_run_id,
            )
            .execution_options(populate_existing=True)
        ).all()
    )
    evidence = list(
        session.exec(
            select(Evidence)
            .where(
                Evidence.governance_report_id == report.id,
                col(Evidence.ip_source_comparison_fact_id).is_not(None),
            )
            .execution_options(populate_existing=True)
        ).all()
    )
    return facts, evidence


def _validated_comparison_bindings(
    *,
    report: GovernanceReport,
    canonical: CanonicalReportV2,
    facts: list[IPSourceComparisonFact],
    evidence: list[Evidence],
) -> tuple[ReportComparisonEvidenceBinding, ...]:
    comparison = canonical.report.ip_source_comparison
    expected = {
        _fact_values(comparison, row)["id"]: _fact_values(comparison, row)
        for row in comparison.results
    }
    _require(len(facts) == len(expected))
    for fact in facts:
        values = expected.get(fact.id)
        _require(values is not None)
        assert values is not None
        _require(all(getattr(fact, key) == value for key, value in values.items()))
    by_id = {item.id: item for item in evidence}
    entries = canonical.evidence_plan.comparison_entries
    _require(len(by_id) == len(evidence) == len(entries))
    rows = {row.canonical_ip: row for row in comparison.results}
    bindings = []
    for index, entry in enumerate(entries):
        reference = entry.evidence_reference
        fact_id = uuid.UUID(reference.fact_id)
        evidence_id = comparison_evidence_id(report.id, index, fact_id)
        item = by_id.get(evidence_id)
        _require(item is not None)
        assert item is not None
        _require(
            item.tenant_id == report.tenant_id
            and item.project_id == report.project_id
            and item.governance_run_id == report.governance_run_id
            and item.governance_report_id == report.id
            and item.ip_source_comparison_fact_id == fact_id
            and item.source_snapshot_id is None
            and item.observation_id is None
            and item.finding_occurrence_id is None
            and item.finding_transition_id is None
        )
        bindings.append(
            ReportComparisonEvidenceBinding(
                evidence_id=evidence_id,
                evidence_reference=reference,
                fact=rows[entry.canonical_ip],
            )
        )
    return tuple(bindings)


def _validated_governance_bindings(
    *,
    session: Session,
    report: GovernanceReport,
    canonical: CanonicalReportV2,
) -> None:
    evidence = session.exec(
        select(Evidence).where(
            Evidence.governance_report_id == report.id,
            col(Evidence.ip_source_comparison_fact_id).is_(None),
        )
    ).all()
    entries = canonical.evidence_plan.entries
    _require(len(evidence) == len(entries))
    by_id = {item.id: item for item in evidence}
    targets: dict[
        str,
        tuple[
            type[SourceSnapshot | Observation | FindingOccurrence | FindingTransition],
            str,
        ],
    ] = {
        "SOURCE_SNAPSHOT": (SourceSnapshot, "source_snapshot_id"),
        "OBSERVATION": (Observation, "observation_id"),
        "FINDING_OCCURRENCE": (FindingOccurrence, "finding_occurrence_id"),
        "FINDING_TRANSITION": (FindingTransition, "finding_transition_id"),
    }
    for index, entry in enumerate(entries):
        reference = entry.evidence_reference
        fact_id = uuid.UUID(reference.fact_id)
        evidence_id = uuid.uuid5(
            report.id, f"{index}:{reference.fact_type}:{reference.fact_id}"
        )
        item = by_id.get(evidence_id)
        _require(item is not None)
        assert item is not None
        model, column = targets[reference.fact_type]
        _require(
            item.tenant_id == report.tenant_id
            and item.project_id == report.project_id
            and item.governance_run_id == report.governance_run_id
            and getattr(item, column) == fact_id
            and sum(getattr(item, name) is not None for _, name in targets.values())
            == 1
        )
        target = session.exec(
            select(model).where(
                model.id == fact_id,
                model.tenant_id == report.tenant_id,
                model.project_id == report.project_id,
                model.governance_run_id == report.governance_run_id,
            )
        ).one_or_none()
        _require(target is not None)
        if isinstance(target, (FindingOccurrence, FindingTransition)):
            _require(str(target.finding_id) == entry.finding_id)
        if (
            isinstance(target, FindingTransition)
            and entry.coverage == "CURRENT_RUN_TRANSITION"
        ):
            _require(target.transition_type == entry.transition_type)


def _fresh_facts(
    *,
    session: Session,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
) -> FrozenReportCandidateFacts:
    # A separate identity map on the SAME transaction prevents cached ORM rows
    # from being mistaken for a fresh database proof. It never owns commit.
    with Session(
        bind=session.connection(), join_transaction_mode="rollback_only"
    ) as reader:
        return read_report_candidate_facts(
            session=reader,
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
        )


def _map_error(
    error: ReportCandidateError | IPSourceComparisonError,
) -> ReportComparisonEvidenceError:
    return ReportComparisonEvidenceError(
        "comparison_contract_unsupported"
        if error.code == "comparison_contract_unsupported"
        else "comparison_evidence_invalid"
    )


def bind_report_comparison_evidence(
    *,
    session: Session,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    report_id: uuid.UUID,
    frozen_facts: FrozenReportCandidateFacts,
    candidate: ReportCandidate,
) -> tuple[ReportComparisonEvidenceBinding, ...]:
    """Validate fresh fixed inputs and bind, without committing or publishing."""
    try:
        with session.no_autoflush:
            report, run = _scoped_report(
                session=session,
                tenant_id=tenant_id,
                project_id=project_id,
                report_id=report_id,
            )
            _require(run.id == run_id)
            _require(
                candidate.report_contract_version == REPORT_V2_CONTRACT_VERSION,
                "report_contract_unsupported",
            )
            _require_binding_stage(session=session, run=run)
            # The lock also serializes the database late-write guards.
            session.exec(
                select(GovernanceRun)
                .where(GovernanceRun.id == run_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).one()
            _require_binding_stage(session=session, run=run)
            session.refresh(report)
            _require(
                report.report_contract_version == REPORT_V2_CONTRACT_VERSION
                and run.report_contract_version == REPORT_V2_CONTRACT_VERSION,
                "report_contract_unsupported",
            )
            fresh = _fresh_facts(
                session=session,
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
            )
            _require(fresh == frozen_facts)
            validate_report_candidate(fresh, candidate)
            canonical = _report_matches_candidate(
                session=session, report=report, candidate=candidate
            )
            facts, evidence = _comparison_records(session=session, report=report)
            if not facts and not evidence:
                facts = [
                    IPSourceComparisonFact(**_fact_values(fresh.comparison, row))
                    for row in fresh.comparison.results
                ]
                session.add_all(facts)
                if facts:
                    session.flush(facts)
                evidence = [
                    Evidence(
                        id=comparison_evidence_id(
                            report_id,
                            index,
                            uuid.UUID(entry.evidence_reference.fact_id),
                        ),
                        tenant_id=tenant_id,
                        project_id=project_id,
                        governance_run_id=run_id,
                        governance_report_id=report_id,
                        ip_source_comparison_fact_id=uuid.UUID(
                            entry.evidence_reference.fact_id
                        ),
                    )
                    for index, entry in enumerate(
                        canonical.evidence_plan.comparison_entries
                    )
                ]
                session.add_all(evidence)
                if evidence:
                    session.flush(evidence)
            return _validated_comparison_bindings(
                report=report,
                canonical=canonical,
                facts=facts,
                evidence=evidence,
            )
    except (ReportCandidateError, IPSourceComparisonError) as error:
        raise _map_error(error) from None
    except ValidationError, ValueError, TypeError, KeyError:
        raise ReportComparisonEvidenceError("comparison_evidence_invalid") from None


def read_report_comparison_evidence(
    *,
    session: Session,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    report_id: uuid.UUID,
) -> tuple[ReportComparisonEvidenceBinding, ...]:
    """Resolve a whole published group once, solely from immutable DB facts."""
    try:
        with Session(
            bind=session.connection(), join_transaction_mode="rollback_only"
        ) as reader:
            report, run = _scoped_report(
                session=reader,
                tenant_id=tenant_id,
                project_id=project_id,
                report_id=report_id,
            )
            _require(
                run.status in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}
                and run.completed_at is not None,
                "report_not_ready",
            )
            fresh = read_report_candidate_facts(
                session=reader,
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run.id,
            )
            candidate = generate_report_candidate(fresh, REPORT_V2_CONTRACT_VERSION)
            canonical = _report_matches_candidate(
                session=reader, report=report, candidate=candidate
            )
            steps = {
                step.step_code: step
                for step in reader.exec(
                    select(RunStep).where(
                        RunStep.governance_run_id == run.id,
                        col(RunStep.step_code).in_(("BUILD_REPORT", "VALIDATE_REPORT")),
                    )
                ).all()
            }
            _require(set(steps) == {"BUILD_REPORT", "VALIDATE_REPORT"})
            html = reader.get(Artifact, report.html_artifact_id)
            csv = reader.get(Artifact, report.csv_artifact_id)
            assert html is not None and csv is not None
            build_hash = hashlib.sha256(
                _canonical_bytes(
                    {
                        "report_contract_version": REPORT_V2_CONTRACT_VERSION,
                        "canonical_json_sha256": candidate.rendered.canonical_json_sha256,
                        "html_sha256": report.html_sha256,
                        "csv_sha256": report.csv_sha256,
                        "html_storage_key": html.storage_key,
                        "csv_storage_key": csv.storage_key,
                    }
                )
            ).hexdigest()
            validation_hash = hashlib.sha256(
                _canonical_bytes(
                    {
                        "build_output_hash": build_hash,
                        "canonical_json_sha256": candidate.rendered.canonical_json_sha256,
                        "html_sha256": report.html_sha256,
                        "csv_sha256": report.csv_sha256,
                    }
                )
            ).hexdigest()
            _require(
                steps["BUILD_REPORT"].status == "SUCCEEDED"
                and steps["BUILD_REPORT"].output_hash == build_hash
                and steps["VALIDATE_REPORT"].status == "SUCCEEDED"
                and steps["VALIDATE_REPORT"].input_hash == build_hash
                and steps["VALIDATE_REPORT"].output_hash == validation_hash
            )
            publication = reader.exec(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.project_id == project_id,
                    AuditEvent.target_type == "governance_run",
                    AuditEvent.target_id == run.id,
                    AuditEvent.action == "governance_run.published",
                )
            ).one_or_none()
            _require(
                publication is not None
                and publication.after_data is not None
                and publication.after_data.get("governance_report_id") == str(report_id)
            )
            facts, evidence = _comparison_records(session=reader, report=report)
            bindings = _validated_comparison_bindings(
                report=report,
                canonical=canonical,
                facts=facts,
                evidence=evidence,
            )
            _validated_governance_bindings(
                session=reader, report=report, canonical=canonical
            )
            return bindings
    except (ReportCandidateError, IPSourceComparisonError) as error:
        raise _map_error(error) from None
    except ValidationError, ValueError, TypeError, KeyError:
        raise ReportComparisonEvidenceError("comparison_evidence_invalid") from None
