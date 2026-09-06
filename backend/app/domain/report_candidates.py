"""Internal, bytes-only report candidates; never publish or choose a Run pin."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import ipaddress
import json
import uuid
from collections import Counter
from collections.abc import Mapping
from types import UnionType
from typing import Annotated, Literal, Self, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.domain.comparison_evidence import (
    ReportV2EvidenceBundle,
    select_comparison_evidence,
    validate_comparison,
)
from app.domain.evidence_selector import (
    EvidenceBundle,
    EvidenceSelectorError,
    FrozenRunEvidenceFacts,
    select_evidence,
)
from app.domain.ip_consistency import (
    IP_PROCESSING_CONTRACT_VERSION,
    IPRecordContractError,
    normalize_ip,
)
from app.domain.ip_source_comparison import (
    COMPARISON_CONTRACT_VERSION,
    IPSourceComparisonError,
    RunIPSourceComparison,
)
from app.domain.netflow_activity import (
    NETFLOW_ACTIVITY_CONTRACT_VERSION,
    NetFlowIPActivityResult,
    netflow_activity_output_hash,
)
from app.domain.report_core import (
    REPORT_CONTRACT_VERSION,
    BoundedEvidenceExamples,
    CanonicalReportCore,
    CurrentRunLifecycleChanges,
    FindingTypeDirectionsAndLimitations,
    FrozenRunReportFacts,
    IPConsistencySummary,
    OpenBacklogAsOfRun,
    Provenance,
    ReportCoreError,
    ReportIdentity,
    compile_report_core,
)
from app.domain.report_renderer import (
    RenderedReport,
    ReportRendererError,
    _canonical_json_value,
    _render_html,
    _safe_csv_cell,
    _validate_evidence,
    _validated_inputs,
    render_report,
)

REPORT_V2_CONTRACT_VERSION: Literal["deterministic-report-v2"] = (
    "deterministic-report-v2"
)
COMPARISON_HTML_LIMIT = 100
COMPARISON_CSV_COLUMNS = (
    "contract_version",
    "tenant_id",
    "project_id",
    "governance_run_id",
    "resource_id",
    "canonical_ip",
    "customer_upload_present",
    "cloudatlas_present",
    "netflow_status",
    "classification",
    "classification_reason",
    "netflow_reason",
    "content_hash",
)
Count = Annotated[int, Field(strict=True, ge=0)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ReportCandidateError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CandidateSourceSnapshot(_FrozenModel):
    source_type: Literal["CUSTOMER_UPLOAD", "CLOUDATLAS", "NETFLOW"]
    source_snapshot_id: uuid.UUID
    content_sha256: Digest
    schema_version: Annotated[str, Field(min_length=1)]
    record_count: Count


class CandidateInputCompleteness(_FrozenModel):
    complete: Literal[True] = True
    sources: tuple[CandidateSourceSnapshot, ...]


class PresenceCapability(_FrozenModel):
    source_snapshot_id: uuid.UUID
    capability: Literal["IP_PRESENCE"] = "IP_PRESENCE"
    status: Literal["COMPLETED"] = "COMPLETED"
    resource_count: Count


class NetFlowCapability(_FrozenModel):
    input_state: Literal["absent", "present"]
    source_snapshot_id: uuid.UUID | None
    capability: Literal["POSITIVE_IP_ACTIVITY"] = "POSITIVE_IP_ACTIVITY"
    status: Literal["NOT_REQUESTED", "COMPLETED"]
    positive_activity_resource_count: Count | None
    coverage: Literal["UNKNOWN"] = "UNKNOWN"


class InputCapabilities(_FrozenModel):
    customer_upload: PresenceCapability
    cloudatlas: PresenceCapability
    netflow: NetFlowCapability


class ClassificationCounts(_FrozenModel):
    matched: Count
    customer_upload_only: Count
    cloudatlas_only: Count
    neither_source_observed: Count


class NetFlowStatusCounts(_FrozenModel):
    ACTIVE: Count
    UNKNOWN: Count


class NetFlowReasonCounts(_FrozenModel):
    positive_activity_observed: Count
    netflow_input_absent: Count
    no_positive_activity_evidence: Count


class ComparisonSummary(_FrozenModel):
    resource_count: Count
    classification_counts: ClassificationCounts
    netflow_status_counts: NetFlowStatusCounts
    netflow_reason_counts: NetFlowReasonCounts

    @classmethod
    def from_comparison(cls, comparison: RunIPSourceComparison) -> Self:
        rows = comparison.results
        classifications = Counter(row.classification for row in rows)
        statuses: Counter[str] = Counter(row.netflow_status for row in rows)
        reasons = Counter(row.netflow_reason for row in rows)
        return cls(
            resource_count=len(rows),
            classification_counts=ClassificationCounts(
                **{
                    key: classifications[key]
                    for key in ClassificationCounts.model_fields
                }
            ),
            netflow_status_counts=NetFlowStatusCounts(
                **{key: statuses[key] for key in NetFlowStatusCounts.model_fields}
            ),
            netflow_reason_counts=NetFlowReasonCounts(
                **{key: reasons[key] for key in NetFlowReasonCounts.model_fields}
            ),
        )


def _capabilities(
    sources: tuple[CandidateSourceSnapshot, ...],
    comparison: RunIPSourceComparison,
) -> InputCapabilities:
    present = len(sources) == 3
    rows = comparison.results
    return InputCapabilities(
        customer_upload=PresenceCapability(
            source_snapshot_id=sources[0].source_snapshot_id,
            resource_count=sum(row.customer_upload_present for row in rows),
        ),
        cloudatlas=PresenceCapability(
            source_snapshot_id=sources[1].source_snapshot_id,
            resource_count=sum(row.cloudatlas_present for row in rows),
        ),
        netflow=NetFlowCapability(
            input_state="present" if present else "absent",
            source_snapshot_id=sources[2].source_snapshot_id if present else None,
            status="COMPLETED" if present else "NOT_REQUESTED",
            positive_activity_resource_count=sum(
                row.netflow_status == "ACTIVE" for row in rows
            )
            if present
            else None,
        ),
    )


def _validate_wire_fields(value: object, annotation: object) -> None:
    """Require complete canonical fields without coercing counts or booleans."""
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is UnionType:
        if value is not None:
            _validate_wire_fields(
                value, next(item for item in arguments if item is not type(None))
            )
    elif origin is tuple:
        if isinstance(value, (tuple, list)):
            for item in value:
                _validate_wire_fields(item, arguments[0])
    elif origin is Literal:
        if not any(type(value) is type(item) and value == item for item in arguments):
            raise ValueError("canonical literal invalid")
    elif annotation is int:
        if type(value) is not int or value < 0:
            raise ValueError("canonical count invalid")
    elif annotation is bool:
        if type(value) is not bool:
            raise ValueError("canonical boolean invalid")
    elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="python")
        if isinstance(value, Mapping):
            for name, field in annotation.model_fields.items():
                if name not in value:
                    raise ValueError("canonical field missing")
                _validate_wire_fields(value[name], field.annotation)


class ReportV2(_FrozenModel):
    report_identity: ReportIdentity
    input_completeness: CandidateInputCompleteness
    ip_consistency_summary: IPConsistencySummary
    current_run_lifecycle_changes: CurrentRunLifecycleChanges
    open_backlog_as_of_run: OpenBacklogAsOfRun
    bounded_evidence_examples: BoundedEvidenceExamples
    bounded_comparison_evidence_examples: BoundedEvidenceExamples
    finding_type_directions_and_limitations: FindingTypeDirectionsAndLimitations
    provenance: Provenance
    input_capabilities: InputCapabilities
    ip_source_comparison: RunIPSourceComparison
    ip_source_comparison_summary: ComparisonSummary

    @model_validator(mode="before")
    @classmethod
    def validate_wire_fields(cls, data: object) -> object:
        _validate_wire_fields(data, cls)
        return data

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        identity = self.report_identity
        comparison = self.ip_source_comparison
        sources = self.input_completeness.sources
        source_types = tuple(source.source_type for source in sources)
        if source_types not in (
            ("CUSTOMER_UPLOAD", "CLOUDATLAS"),
            ("CUSTOMER_UPLOAD", "CLOUDATLAS", "NETFLOW"),
        ):
            raise ValueError("report sources invalid")
        if len({source.source_snapshot_id for source in sources}) != len(sources):
            raise ValueError("duplicate snapshot")
        if (
            identity.report_contract_version != REPORT_V2_CONTRACT_VERSION
            or identity.project_id != str(comparison.project_id)
            or identity.governance_run_id != str(comparison.governance_run_id)
            or identity.governance_run_id != self.provenance.governance_run_id
            or identity.governance_run_id
            != self.open_backlog_as_of_run.as_of_governance_run_id
        ):
            raise ValueError("report scope or version differs")
        if self.provenance.source_snapshot_ids != tuple(
            str(source.source_snapshot_id) for source in sources
        ) or self.provenance.source_snapshot_hashes != tuple(
            source.content_sha256 for source in sources
        ):
            raise ValueError("provenance differs")
        validate_comparison(comparison, netflow_present=len(sources) == 3)
        expected_capabilities = _capabilities(sources, comparison)
        if self.input_capabilities != expected_capabilities:
            raise ValueError("capabilities differ")
        if self.ip_source_comparison_summary != ComparisonSummary.from_comparison(
            comparison
        ):
            raise ValueError("comparison summary differs")
        summary = self.ip_consistency_summary
        if (
            summary.customer_observed_asset_count
            != expected_capabilities.customer_upload.resource_count
            or summary.cloudatlas_observed_asset_count
            != expected_capabilities.cloudatlas.resource_count
            or summary.matched_asset_count
            != sum(
                row.customer_upload_present and row.cloudatlas_present
                for row in comparison.results
            )
        ):
            raise ValueError("dual-source summary differs")
        return self


class CanonicalReportV2(_FrozenModel):
    schema_version: Literal["deterministic-report-v2"] = "deterministic-report-v2"
    report: ReportV2
    evidence_plan: ReportV2EvidenceBundle

    @model_validator(mode="before")
    @classmethod
    def validate_wire_fields(cls, data: object) -> object:
        _validate_wire_fields(data, cls)
        return data

    @model_validator(mode="after")
    def validate_evidence_scope(self) -> Self:
        identity = self.report.report_identity
        if (
            self.evidence_plan.report_contract_version != REPORT_V2_CONTRACT_VERSION
            or self.evidence_plan.governance_run_id != identity.governance_run_id
        ):
            raise ValueError("evidence scope or version differs")
        if any(
            entry.evidence_reference.governance_run_id != identity.governance_run_id
            for entry in self.evidence_plan.entries
        ):
            raise ValueError("evidence target scope differs")
        if self.evidence_plan.comparison_entries != select_comparison_evidence(
            self.report.ip_source_comparison
        ):
            raise ValueError("comparison evidence selection differs")
        try:
            _validate_evidence(
                self.report,
                EvidenceBundle(
                    governance_run_id=identity.governance_run_id,
                    report_contract_version=REPORT_V2_CONTRACT_VERSION,
                    entries=self.evidence_plan.entries,
                ),
            )
        except ReportRendererError:
            raise ValueError("governance evidence plan invalid") from None
        return self


class FrozenGovernanceCandidateFacts(_FrozenModel):
    governance: FrozenRunReportFacts
    evidence: FrozenRunEvidenceFacts

    @model_validator(mode="after")
    def validate_evidence_scope(self) -> Self:
        if self.evidence.governance_run_id != self.governance.run_id or any(
            reference.governance_run_id != self.governance.run_id
            for reference in self.evidence.available_facts
        ):
            raise ValueError("evidence catalog scope differs")
        return self


class FrozenReportCandidateFacts(FrozenGovernanceCandidateFacts):
    comparison: RunIPSourceComparison
    netflow_snapshot: CandidateSourceSnapshot | None
    netflow_activity: NetFlowIPActivityResult | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_comparison_version(cls, data: object) -> object:
        if isinstance(data, Mapping):
            comparison = data.get("comparison")
            if isinstance(comparison, RunIPSourceComparison):
                version: object = comparison.contract_version
            elif isinstance(comparison, Mapping):
                version = comparison.get("contract_version")
            else:
                return data
            if version is not None and version != COMPARISON_CONTRACT_VERSION:
                raise IPSourceComparisonError("comparison_contract_unsupported")
            _validate_wire_fields(comparison, RunIPSourceComparison)
        return data

    @model_validator(mode="after")
    def validate_scope_and_comparison(self) -> Self:
        facts, comparison = self.governance, self.comparison
        if facts.processing_contract_version != IP_PROCESSING_CONTRACT_VERSION:
            raise IPSourceComparisonError("comparison_contract_unsupported")
        if (
            facts.run_id != str(comparison.governance_run_id)
            or facts.project_id != str(comparison.project_id)
            or self.evidence.governance_run_id != facts.run_id
        ):
            raise ValueError("candidate scope differs")
        if (
            self.netflow_snapshot is not None
            and self.netflow_snapshot.source_type != "NETFLOW"
        ):
            raise ValueError("netflow snapshot type differs")
        validate_comparison(
            comparison, netflow_present=self.netflow_snapshot is not None
        )
        if self.netflow_snapshot is None:
            if self.netflow_activity is not None:
                raise ValueError("absent input has activity proof")
        else:
            activity_result = self.netflow_activity
            if activity_result is None:
                raise ValueError("present input requires complete activity result")
            if activity_result.contract_version != NETFLOW_ACTIVITY_CONTRACT_VERSION:
                raise IPSourceComparisonError("comparison_contract_unsupported")
            activity_keys = []
            for activity in activity_result.activities:
                if (
                    type(activity.flow_count) is not int
                    or activity.flow_count <= 0
                    or normalize_ip(activity.canonical_ip) != activity.canonical_ip
                    or not activity.protocols
                ):
                    raise ValueError("invalid positive activity")
                activity_keys.append(activity.canonical_ip)
                expected_peers = tuple(
                    sorted(
                        set(activity.peer_ips),
                        key=lambda value: (
                            ipaddress.ip_address(value).version,
                            int(ipaddress.ip_address(value)),
                        ),
                    )
                )
                if activity.peer_ips != expected_peers or any(
                    normalize_ip(peer) != peer for peer in activity.peer_ips
                ):
                    raise ValueError("activity peer set invalid")
                if activity.protocols != tuple(sorted(set(activity.protocols))) or any(
                    type(value) is not int or not 0 <= value <= 255
                    for value in activity.protocols
                ):
                    raise ValueError("activity protocols invalid")
                for timestamp in (activity.first_seen_utc, activity.last_seen_utc):
                    if timestamp is not None and (
                        timestamp.tzinfo is None
                        or timestamp.utcoffset() is None
                        or timestamp.microsecond != 0
                    ):
                        raise ValueError("activity timestamp invalid")
                if (
                    activity.first_seen_utc is not None
                    and activity.last_seen_utc is not None
                    and activity.first_seen_utc > activity.last_seen_utc
                ):
                    raise ValueError("activity interval invalid")
            expected_active_keys = [
                row.canonical_ip
                for row in comparison.results
                if row.netflow_status == "ACTIVE"
            ]
            if activity_keys != expected_active_keys:
                raise ValueError("activity set differs from comparison")
            if activity_result.output_hash != netflow_activity_output_hash(
                activity_result.activities
            ):
                raise ValueError("activity result hash differs")
        if set(facts.customer_observed_resource_keys) != {
            row.canonical_ip
            for row in comparison.results
            if row.customer_upload_present
        }:
            raise ValueError("customer membership differs")
        if set(facts.cloudatlas_observed_resource_keys) != {
            row.canonical_ip for row in comparison.results if row.cloudatlas_present
        }:
            raise ValueError("cloudatlas membership differs")
        return self


class ReportCandidate(_FrozenModel):
    report_contract_version: str
    report: ReportV2 | CanonicalReportCore
    evidence_plan: EvidenceBundle | ReportV2EvidenceBundle
    rendered: RenderedReport


def _comparison_html(
    report: ReportV2, evidence: ReportV2EvidenceBundle
) -> tuple[str, ...]:
    comparison = report.ip_source_comparison
    rows = comparison.results[:COMPARISON_HTML_LIMIT]
    total, shown = len(comparison.results), len(rows)
    sections = [
        '<section id="input-capabilities"><h2>输入能力</h2>',
        "<p>能力仅表示已执行的确定性计算，不表示完整覆盖。</p>",
        "<dl>",
    ]
    for source, capability in report.input_capabilities.model_dump(mode="json").items():
        sections.append(f"<dt>{html.escape(source)}</dt>")
        for key, value in capability.items():
            sections.append(
                f"<dd>{html.escape(key)}: {html.escape(str(value)) if value is not None else 'null'}</dd>"
            )
    sections.extend(
        [
            "</dl></section>",
            '<section id="ip-source-comparison-summary"><h2>三来源比较汇总</h2>',
            f"<p>资源总数：{total}</p><dl>",
        ]
    )
    for category, counts in report.ip_source_comparison_summary.model_dump().items():
        if isinstance(counts, dict):
            sections.append(f"<dt>{html.escape(category)}</dt>")
            sections.extend(
                f"<dd>{html.escape(key)}: {value}</dd>" for key, value in counts.items()
            )
    sections.extend(
        [
            "</dl></section>",
            '<section id="ip-source-comparison"><h2>三来源资产比较</h2>',
            "<p>matched 仅表示双来源出现；only 仅比较 CustomerUpload/CloudAtlas；UNKNOWN 不表示不存在或无流量；NetFlow 仅提供正向活动，覆盖范围 UNKNOWN。</p>",
            f"<p>总条数：{total}；展示条数：{shown}；截断：{'是' if total > shown else '否'}。</p>",
        ]
    )
    if not rows:
        sections.append("<p>本 Run 无可比较的资产；这不表示资产不存在。</p>")
    else:
        sections.append(
            '<div role="region" aria-label="三来源资产比较表" tabindex="0" style="max-width:100%;overflow-x:auto"><table><caption>按 Canonical IP 数值排序的资产比较</caption><thead><tr>'
        )
        columns = COMPARISON_CSV_COLUMNS[4:]
        sections.extend(
            f'<th scope="col">{html.escape(column)}</th>' for column in columns
        )
        sections.append("</tr></thead><tbody>")
        for row in rows:
            values = row.model_dump(mode="json")
            sections.append("<tr>")
            for column in columns:
                value = values[column]
                text = str(value).lower() if isinstance(value, bool) else str(value)
                sections.append(f"<td>{html.escape(text)}</td>")
            sections.append("</tr>")
        sections.append("</tbody></table></div>")
    sections.append("</section>")
    selected = evidence.comparison_entries
    rendered = selected[:8]
    sections.extend(
        [
            '<section id="comparison-evidence-examples"><h2>比较 Evidence 示例</h2>',
            f"<p>总比较数：{total}；入选 Evidence 数：{len(selected)}；实际展示数：{len(rendered)}；选择截断：{'是' if total > len(selected) else '否'}；展示截断：{'是' if len(selected) > len(rendered) else '否'}。</p>",
            "<p>独立上限：入选 50 条，展示 8 条；样本不保证覆盖每种分类。以下稳定 ID / Hash 为待绑定文字引用，不表示已持久化或已发布。</p>",
        ]
    )
    if not rendered:
        sections.append("<p>无可展示的比较 Evidence 示例。</p>")
    for index, (entry, row) in enumerate(
        zip(rendered, comparison.results[:8], strict=True), start=1
    ):
        reference = entry.evidence_reference
        sections.extend(
            [
                f'<article class="comparison-evidence-card" id="comparison-evidence-card-{index}">',
                f"<h3>比较 Evidence {index}</h3>",
                f"<p>Canonical IP：<code>{html.escape(entry.canonical_ip)}</code></p>",
                f"<p>Classification：{html.escape(row.classification)}；Reason：{html.escape(row.classification_reason)}</p>",
                f"<p>NetFlow：{html.escape(row.netflow_status)}；Reason：{html.escape(row.netflow_reason)}</p>",
                f"<p>来源事实：{html.escape(reference.fact_type)} / <code>{html.escape(reference.fact_id)}</code></p>",
                f"<p>内容 SHA-256：<code>{html.escape(reference.content_hash)}</code></p>",
                "</article>",
            ]
        )
    sections.append("</section>")
    return tuple(sections)


def _comparison_csv(comparison: RunIPSourceComparison) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(COMPARISON_CSV_COLUMNS)
    scope = (
        comparison.contract_version,
        comparison.tenant_id,
        comparison.project_id,
        comparison.governance_run_id,
    )
    for row in comparison.results:
        values = row.model_dump(mode="json")
        writer.writerow(
            tuple(
                _safe_csv_cell(value)
                for value in (
                    *scope,
                    *(
                        str(values[column]).lower()
                        if isinstance(values[column], bool)
                        else values[column]
                        for column in COMPARISON_CSV_COLUMNS[4:]
                    ),
                )
            )
        )
    return stream.getvalue().encode("utf-8")


def _render_v2(report: ReportV2, evidence: ReportV2EvidenceBundle) -> RenderedReport:
    envelope = CanonicalReportV2(
        schema_version=REPORT_V2_CONTRACT_VERSION, report=report, evidence_plan=evidence
    )
    payload = _canonical_json_value(envelope.model_dump(mode="python"))
    canonical_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    html_bytes = _render_html(
        report,
        evidence,
        extra_sections=_comparison_html(report, evidence),
        internal_candidate=True,
    )
    csv_bytes = _comparison_csv(report.ip_source_comparison)
    return RenderedReport(
        canonical_json=canonical_json,
        html=html_bytes,
        csv=csv_bytes,
        canonical_json_sha256=hashlib.sha256(canonical_json).hexdigest(),
        html_sha256=hashlib.sha256(html_bytes).hexdigest(),
        csv_sha256=hashlib.sha256(csv_bytes).hexdigest(),
    )


def generate_report_candidate(
    frozen_facts: FrozenGovernanceCandidateFacts | Mapping[str, object],
    report_contract_version: str | None,
) -> ReportCandidate:
    """Generate complete in-memory bytes; no DB, file writes or model calls."""
    if report_contract_version not in {
        REPORT_CONTRACT_VERSION,
        REPORT_V2_CONTRACT_VERSION,
    }:
        raise ReportCandidateError("report_contract_unsupported")
    try:
        if report_contract_version == REPORT_CONTRACT_VERSION:
            # Dispatch before touching comparison/NetFlow proof: typed and
            # serialized fixed bundles have the same v1 dependencies.
            data: Mapping[str, object] = (
                {
                    "governance": frozen_facts.governance.model_dump(mode="python"),
                    "evidence": frozen_facts.evidence.model_dump(mode="python"),
                }
                if isinstance(frozen_facts, FrozenGovernanceCandidateFacts)
                else {
                    key: value
                    for key, value in frozen_facts.items()
                    if key not in {"comparison", "netflow_snapshot", "netflow_activity"}
                }
            )
            governance_facts = FrozenGovernanceCandidateFacts.model_validate(data)
            governance = compile_report_core(
                governance_facts.governance, REPORT_CONTRACT_VERSION
            )
            evidence = select_evidence(
                governance_facts.evidence, REPORT_CONTRACT_VERSION
            )
            return ReportCandidate(
                report_contract_version=REPORT_CONTRACT_VERSION,
                report=governance,
                evidence_plan=evidence,
                rendered=render_report(governance, evidence),
            )
        data = (
            frozen_facts.model_dump(mode="python")
            if isinstance(frozen_facts, FrozenGovernanceCandidateFacts)
            else frozen_facts
        )
        facts = FrozenReportCandidateFacts.model_validate(data)
        governance = compile_report_core(facts.governance, REPORT_CONTRACT_VERSION)
        if {
            (
                item.finding_id,
                item.finding_type,
                item.canonical_ip,
                item.transition_type,
            )
            for item in facts.evidence.current_run_transitions
        } != {
            (
                item.finding_id,
                item.finding_type,
                item.canonical_ip,
                item.transition_type,
            )
            for item in governance.current_run_lifecycle_changes.changes
        } or {
            (item.finding_id, item.finding_type, item.canonical_ip)
            for item in facts.evidence.open_backlog
        } != {
            (item.finding_id, item.finding_type, item.canonical_ip)
            for item in governance.open_backlog_as_of_run.findings
        }:
            raise ValueError("governance evidence coverage differs")
        evidence = select_evidence(facts.evidence, REPORT_CONTRACT_VERSION)
        # Reuse the existing governance/Evidence integrity checks without
        # rendering unused v1 artifacts.
        _validated_inputs(governance, evidence)
        sources = tuple(
            CandidateSourceSnapshot.model_validate(
                snapshot.model_dump(exclude={"complete"})
            )
            for snapshot in facts.governance.source_snapshots
        )
        sources = tuple(
            sorted(
                sources,
                key=lambda source: ("CUSTOMER_UPLOAD", "CLOUDATLAS").index(
                    source.source_type
                ),
            )
        )
        if facts.netflow_snapshot is not None:
            sources = (*sources, facts.netflow_snapshot)
        report_data = governance.model_dump(mode="python")
        report_data["report_identity"]["report_contract_version"] = (
            REPORT_V2_CONTRACT_VERSION
        )
        report_data["input_completeness"] = CandidateInputCompleteness(sources=sources)
        report_data["provenance"]["source_snapshot_ids"] = tuple(
            str(source.source_snapshot_id) for source in sources
        )
        report_data["provenance"]["source_snapshot_hashes"] = tuple(
            source.content_sha256 for source in sources
        )
        report_data.update(
            bounded_comparison_evidence_examples=BoundedEvidenceExamples(),
            input_capabilities=_capabilities(sources, facts.comparison),
            ip_source_comparison=facts.comparison,
            ip_source_comparison_summary=ComparisonSummary.from_comparison(
                facts.comparison
            ),
        )
        report = ReportV2.model_validate(report_data)
        v2_evidence = ReportV2EvidenceBundle(
            governance_run_id=evidence.governance_run_id,
            report_contract_version=REPORT_V2_CONTRACT_VERSION,
            max_entries=100,
            entries=evidence.entries,
            comparison_entries=select_comparison_evidence(facts.comparison),
        )
        return ReportCandidate(
            report_contract_version=REPORT_V2_CONTRACT_VERSION,
            report=report,
            evidence_plan=v2_evidence,
            rendered=_render_v2(report, v2_evidence),
        )
    except IPSourceComparisonError as error:
        code = (
            "comparison_contract_unsupported"
            if error.code == "comparison_contract_unsupported"
            else "report_facts_invalid"
        )
        raise ReportCandidateError(code) from None
    except (
        ValidationError,
        ValueError,
        TypeError,
        ReportCoreError,
        EvidenceSelectorError,
        ReportRendererError,
        IPRecordContractError,
    ):
        raise ReportCandidateError("report_facts_invalid") from None


def validate_report_candidate(
    frozen_facts: FrozenGovernanceCandidateFacts | Mapping[str, object],
    candidate: ReportCandidate,
) -> None:
    """Rebuild from fixed inputs instead of trusting supplied bytes or hashes."""
    expected = generate_report_candidate(
        frozen_facts, candidate.report_contract_version
    )
    try:
        # Revalidate even model_copy/model_construct inputs before comparison.
        candidate_data = candidate.model_dump(mode="python")
        if isinstance(candidate.report, CanonicalReportCore):
            # v1's complete Finding CSV rows are intentionally absent from JSON,
            # but remain part of the validated in-memory candidate contract.
            candidate_data["report"]["finding_export_rows"] = [
                row.model_dump(mode="python")
                for row in candidate.report.finding_export_rows
            ]
        validated = ReportCandidate.model_validate(candidate_data)
    except (
        ValidationError,
        ValueError,
        TypeError,
        IPSourceComparisonError,
        IPRecordContractError,
    ):
        raise ReportCandidateError("report_candidate_invalid") from None
    if validated != expected:
        raise ReportCandidateError("report_candidate_invalid")
