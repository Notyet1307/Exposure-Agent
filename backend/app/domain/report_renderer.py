"""Pure, fail-closed rendering for the deterministic governance report.

The public seam consumes only the already-validated report model and Evidence
plan.  It performs no database, Artifact-storage, model-service, or other I/O.
All three representations and all hashes are prepared before one immutable
result is returned.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import ipaddress
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from urllib.parse import quote

from app.domain.evidence_selector import EvidenceBundle, EvidencePlanEntry
from app.domain.ip_consistency import IPRecordContractError, normalize_ip
from app.domain.report_core import (
    REPORT_CONTRACT_VERSION,
    CanonicalReportCore,
    FindingExportRow,
    FindingType,
    TransitionType,
)

CANONICAL_JSON_SCHEMA_VERSION: Final = REPORT_CONTRACT_VERSION
HTML_EVIDENCE_MAX_ENTRIES: Final = 8
CSV_COLUMNS: Final[tuple[str, ...]] = (
    "report_contract_version",
    "governance_run_id",
    "finding_id",
    "canonical_ip",
    "finding_type",
    "status_as_of_run",
    "current_run_transition",
    "first_occurrence_at",
    "last_occurrence_at",
    "occurrence_count_as_of_run",
    "transition_count_as_of_run",
    "evidence_reference",
    "detail_reference",
)

_FINDING_TYPES: Final[tuple[FindingType, ...]] = (
    "UNREPORTED_ASSET",
    "UNOBSERVED_ASSET",
)
_TRANSITION_TYPES: Final[tuple[TransitionType, ...]] = (
    "OPENED",
    "REOPENED",
    "CLOSED",
)
_FINDING_TYPE_ORDER: Final = {
    value: index for index, value in enumerate(_FINDING_TYPES)
}
_DIRECTIONS: Final = {
    "UNREPORTED_ASSET": "向客户系统补充资产记录",
    "UNOBSERVED_ASSET": "补充扫描目标并重新扫描",
}
_LIMITATIONS: Final = (
    "未观测资产不表示资产不存在",
    "本报告不分配严重性、优先级、责任、置信度或根因",
    "本报告不构成已批准动作，也不提供资产级处置动作",
)


class ReportRendererError(Exception):
    """Stable fail-closed error from the public Renderer seam."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# Short alias for callers that use the component name directly.
RendererError = ReportRendererError


@dataclass(frozen=True, slots=True)
class RenderedReport:
    canonical_json: bytes
    html: bytes
    csv: bytes
    canonical_json_sha256: str
    html_sha256: str
    csv_sha256: str

    @property
    def hashes(self) -> Mapping[str, str]:
        return {
            "canonical_json": self.canonical_json_sha256,
            "html": self.html_sha256,
            "csv": self.csv_sha256,
        }


def _nonblank(value: str) -> bool:
    return bool(value.strip())


def _canonical_ip(value: str) -> bool:
    try:
        return normalize_ip(value) == value
    except IPRecordContractError:
        return False


def _ip_sort_key(value: str) -> tuple[int, int]:
    address = ipaddress.ip_address(value)
    return address.version, int(address)


def _finding_sort_key(
    finding_type: FindingType, canonical_ip: str, finding_id: str
) -> tuple[int, tuple[int, int], str]:
    return _FINDING_TYPE_ORDER[finding_type], _ip_sort_key(canonical_ip), finding_id


def _counts_are_canonical(
    values: tuple[object, ...], expected_types: tuple[str, ...], total: int
) -> bool:
    if len(values) != len(expected_types):
        return False
    actual_total = 0
    for value, expected_type in zip(values, expected_types, strict=True):
        item_type = getattr(value, "finding_type", None) or getattr(
            value, "transition_type", None
        )
        count = getattr(value, "count", None)
        if item_type != expected_type or not isinstance(count, int) or count < 0:
            return False
        actual_total += count
    return actual_total == total


def _validate_report(report: CanonicalReportCore) -> None:
    identity = report.report_identity
    if (
        identity.report_contract_version != REPORT_CONTRACT_VERSION
        or identity.generation_mode != "DETERMINISTIC_TEMPLATE"
        or not all(
            _nonblank(value)
            for value in (
                identity.governance_run_id,
                identity.project_id,
                report.provenance.processing_contract_version,
            )
        )
        or identity.run_completed_at.tzinfo is None
        or identity.run_completed_at.utcoffset() is None
    ):
        raise ReportRendererError("report_schema_invalid")

    sources = report.input_completeness.sources
    if (
        not report.input_completeness.complete
        or tuple(source.source_type for source in sources)
        != ("CUSTOMER_UPLOAD", "CLOUDATLAS")
        or any(
            source.record_count < 0
            or not _nonblank(source.source_snapshot_id)
            or not _nonblank(source.schema_version)
            or len(source.content_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in source.content_sha256
            )
            for source in sources
        )
    ):
        raise ReportRendererError("report_schema_invalid")

    summary = report.ip_consistency_summary
    if (
        min(
            summary.customer_observed_asset_count,
            summary.cloudatlas_observed_asset_count,
            summary.matched_asset_count,
            summary.current_run_finding_count,
        )
        < 0
        or summary.matched_asset_count
        > min(
            summary.customer_observed_asset_count,
            summary.cloudatlas_observed_asset_count,
        )
        or summary.current_run_finding_count
        != (
            summary.customer_observed_asset_count
            + summary.cloudatlas_observed_asset_count
            - (2 * summary.matched_asset_count)
        )
        or summary.all_observed_ip_identities_matched
        != (summary.current_run_finding_count == 0)
        or not _counts_are_canonical(
            summary.finding_counts,
            _FINDING_TYPES,
            summary.current_run_finding_count,
        )
    ):
        raise ReportRendererError("report_schema_invalid")

    changes = report.current_run_lifecycle_changes
    change_keys = [
        _finding_sort_key(change.finding_type, change.canonical_ip, change.finding_id)
        for change in changes.changes
        if _canonical_ip(change.canonical_ip) and _nonblank(change.finding_id)
    ]
    if (
        len(change_keys) != len(changes.changes)
        or change_keys != sorted(change_keys)
        or len({change.finding_id for change in changes.changes})
        != len(changes.changes)
        or changes.total != len(changes.changes)
        or not _counts_are_canonical(
            changes.transition_counts,
            _TRANSITION_TYPES,
            changes.total,
        )
        or Counter(change.transition_type for change in changes.changes)
        != Counter(
            {
                count.transition_type: count.count
                for count in changes.transition_counts
                if count.count
            }
        )
    ):
        raise ReportRendererError("report_schema_invalid")

    backlog = report.open_backlog_as_of_run
    backlog_keys = [
        _finding_sort_key(item.finding_type, item.canonical_ip, item.finding_id)
        for item in backlog.findings
        if _canonical_ip(item.canonical_ip) and _nonblank(item.finding_id)
    ]
    if (
        backlog.as_of_governance_run_id != identity.governance_run_id
        or len(backlog_keys) != len(backlog.findings)
        or backlog_keys != sorted(backlog_keys)
        or len({item.finding_id for item in backlog.findings}) != len(backlog.findings)
        or backlog.total != len(backlog.findings)
        or not _counts_are_canonical(
            backlog.finding_counts,
            _FINDING_TYPES,
            backlog.total,
        )
        or Counter(item.finding_type for item in backlog.findings)
        != Counter(
            {
                count.finding_type: count.count
                for count in backlog.finding_counts
                if count.count
            }
        )
    ):
        raise ReportRendererError("report_schema_invalid")

    evidence_boundary = report.bounded_evidence_examples
    directions = report.finding_type_directions_and_limitations
    present_types = (
        {item.finding_type for item in summary.finding_counts if item.count > 0}
        | {item.finding_type for item in backlog.finding_counts if item.count > 0}
        | {change.finding_type for change in changes.changes}
    )
    if (
        evidence_boundary.selection_owner != "EVIDENCE_SELECTOR"
        or evidence_boundary.max_selected_entries != 50
        or evidence_boundary.max_rendered_entries != HTML_EVIDENCE_MAX_ENTRIES
        or tuple(direction.finding_type for direction in directions.directions)
        != _FINDING_TYPES
        or any(
            direction.direction != _DIRECTIONS[direction.finding_type]
            or direction.present != (direction.finding_type in present_types)
            for direction in directions.directions
        )
        or directions.limitations != _LIMITATIONS
    ):
        raise ReportRendererError("report_schema_invalid")

    provenance = report.provenance
    relevant_finding_ids = {change.finding_id for change in changes.changes} | {
        finding.finding_id for finding in backlog.findings
    }
    if (
        provenance.governance_run_id != identity.governance_run_id
        or provenance.source_snapshot_ids
        != tuple(source.source_snapshot_id for source in sources)
        or provenance.source_snapshot_hashes
        != tuple(source.content_sha256 for source in sources)
        or provenance.finding_lifecycle_fact_count < len(relevant_finding_ids)
    ):
        raise ReportRendererError("report_schema_invalid")

    _validate_export_rows(report)


def _validate_export_rows(report: CanonicalReportCore) -> None:
    identity_by_id: dict[str, tuple[FindingType, str]] = {}
    open_ids: set[str] = set()
    transitions: dict[str, TransitionType] = {}
    for finding in report.open_backlog_as_of_run.findings:
        identity_by_id[finding.finding_id] = (
            finding.finding_type,
            finding.canonical_ip,
        )
        open_ids.add(finding.finding_id)
    for change in report.current_run_lifecycle_changes.changes:
        identity = (change.finding_type, change.canonical_ip)
        existing = identity_by_id.setdefault(change.finding_id, identity)
        if existing != identity:
            raise ReportRendererError("report_schema_invalid")
        transitions[change.finding_id] = change.transition_type

    rows = report.finding_export_rows
    expected_ids = open_ids | set(transitions)
    if (
        len({row.finding_id for row in rows}) != len(rows)
        or {row.finding_id for row in rows} != expected_ids
        or list(rows)
        != sorted(
            rows,
            key=lambda row: _finding_sort_key(
                row.finding_type, row.canonical_ip, row.finding_id
            ),
        )
    ):
        raise ReportRendererError("report_schema_invalid")

    completed_at = report.report_identity.run_completed_at
    for row in rows:
        expected_identity = identity_by_id[row.finding_id]
        if (
            (row.finding_type, row.canonical_ip) != expected_identity
            or row.status_as_of_run
            != ("OPEN" if row.finding_id in open_ids else "CLOSED")
            or row.current_run_transition != transitions.get(row.finding_id)
            or not _canonical_ip(row.canonical_ip)
            or row.first_occurrence_at.tzinfo is None
            or row.first_occurrence_at.utcoffset() is None
            or row.last_occurrence_at.tzinfo is None
            or row.last_occurrence_at.utcoffset() is None
            or row.first_occurrence_at > row.last_occurrence_at
            or row.last_occurrence_at > completed_at
            or row.occurrence_count_as_of_run < 1
            or row.transition_count_as_of_run < 1
        ):
            raise ReportRendererError("report_schema_invalid")


def _validate_evidence(report: CanonicalReportCore, evidence: EvidenceBundle) -> None:
    identity = report.report_identity
    if (
        evidence.governance_run_id != identity.governance_run_id
        or evidence.report_contract_version != identity.report_contract_version
        or evidence.max_entries != 50
        or len(evidence.entries) > evidence.max_entries
    ):
        raise ReportRendererError("evidence_plan_invalid")

    changes = {
        change.finding_id: change
        for change in report.current_run_lifecycle_changes.changes
    }
    backlog = {
        finding.finding_id: finding
        for finding in report.open_backlog_as_of_run.findings
    }
    finding_ids: set[str] = set()
    references: set[tuple[str, str, str]] = set()
    seen_backlog = False
    for entry in evidence.entries:
        reference = entry.evidence_reference
        reference_key = (
            reference.governance_run_id,
            reference.fact_type,
            reference.fact_id,
        )
        if entry.coverage == "CURRENT_RUN_TRANSITION":
            transition_target = changes.get(entry.finding_id)
            target_identity = (
                None
                if transition_target is None
                else (transition_target.finding_type, transition_target.canonical_ip)
            )
            coverage_invalid = (
                transition_target is None
                or seen_backlog
                or entry.transition_type != transition_target.transition_type
                or reference.fact_type != "FINDING_TRANSITION"
            )
        else:
            backlog_target = backlog.get(entry.finding_id)
            target_identity = (
                None
                if backlog_target is None
                else (backlog_target.finding_type, backlog_target.canonical_ip)
            )
            seen_backlog = True
            coverage_invalid = (
                backlog_target is None or entry.transition_type is not None
            )
        if (
            coverage_invalid
            or (entry.finding_type, entry.canonical_ip) != target_identity
            or not _canonical_ip(entry.canonical_ip)
            or reference.governance_run_id != identity.governance_run_id
            or not _nonblank(reference.fact_id)
            or entry.finding_id in finding_ids
            or reference_key in references
        ):
            raise ReportRendererError("evidence_plan_invalid")
        finding_ids.add(entry.finding_id)
        references.add(reference_key)


def _validated_inputs(
    report_model: CanonicalReportCore | Mapping[str, object],
    evidence_plan: EvidenceBundle | Mapping[str, object],
) -> tuple[CanonicalReportCore, EvidenceBundle]:
    try:
        report = (
            report_model
            if isinstance(report_model, CanonicalReportCore)
            else CanonicalReportCore.model_validate(report_model)
        )
        _validate_report(report)
    except ReportRendererError:
        raise
    except Exception:
        raise ReportRendererError("report_schema_invalid") from None

    try:
        evidence = (
            evidence_plan
            if isinstance(evidence_plan, EvidenceBundle)
            else EvidenceBundle.model_validate(evidence_plan)
        )
        _validate_evidence(report, evidence)
    except ReportRendererError:
        raise
    except Exception:
        raise ReportRendererError("evidence_plan_invalid") from None
    return report, evidence


def _canonical_json_value(value: object) -> object:
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, Mapping):
        return {str(key): _canonical_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    return value


def _canonical_json(report: CanonicalReportCore, evidence: EvidenceBundle) -> bytes:
    payload = {
        "schema_version": CANONICAL_JSON_SCHEMA_VERSION,
        "report": _canonical_json_value(report.model_dump(mode="python")),
        "evidence_plan": _canonical_json_value(evidence.model_dump(mode="python")),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _text(value: object) -> str:
    return html.escape(str(value), quote=True)


def _finding_reference(finding_id: str, run_id: str) -> str:
    return f"./findings/{quote(finding_id, safe='')}?run={quote(run_id, safe='')}"


def _evidence_reference(entry: EvidencePlanEntry) -> str:
    reference = entry.evidence_reference
    return (
        f"./evidence/{quote(reference.fact_type, safe='')}/"
        f"{quote(reference.fact_id, safe='')}"
    )


def _render_html(report: CanonicalReportCore, evidence: EvidenceBundle) -> bytes:
    identity = report.report_identity
    summary = report.ip_consistency_summary
    changes = report.current_run_lifecycle_changes
    backlog = report.open_backlog_as_of_run
    sections: list[str] = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>确定性治理报告</title>",
        "<style>body{font-family:sans-serif;line-height:1.5;margin:2rem;max-width:72rem}section{margin:2rem 0}table{border-collapse:collapse}th,td{border:1px solid #bbb;padding:.4rem;text-align:left}.evidence-card{border:1px solid #bbb;padding:1rem;margin:.75rem 0}</style>",
        "</head>",
        "<body>",
        "<h1>确定性治理报告</h1>",
        '<section id="report-identity">',
        "<h2>报告身份与生成模式</h2>",
        f"<p>GovernanceRun：<code>{_text(identity.governance_run_id)}</code></p>",
        f"<p>Project：<code>{_text(identity.project_id)}</code></p>",
        f"<p>完成时间：<time>{_text(_timestamp(identity.run_completed_at))}</time></p>",
        f"<p>报告契约：<code>{_text(identity.report_contract_version)}</code></p>",
        f"<p>生成模式：<strong>{_text(identity.generation_mode)}</strong></p>",
        "</section>",
        '<section id="input-completeness">',
        "<h2>输入完整性</h2>",
        "<p>两个输入 SourceSnapshot 均已完整读取。</p>",
        "<table><thead><tr><th>来源</th><th>Snapshot ID</th><th>内容 SHA-256</th><th>Schema</th><th>记录数</th></tr></thead><tbody>",
    ]
    sections.extend(
        "<tr>"
        f"<td>{_text(source.source_type)}</td>"
        f"<td>{_text(source.source_snapshot_id)}</td>"
        f"<td><code>{_text(source.content_sha256)}</code></td>"
        f"<td>{_text(source.schema_version)}</td>"
        f"<td>{source.record_count}</td>"
        "</tr>"
        for source in report.input_completeness.sources
    )
    sections.extend(
        [
            "</tbody></table>",
            "</section>",
            '<section id="ip-consistency-summary">',
            "<h2>IP 一致性摘要</h2>",
            f"<p>客户侧观测资产：{summary.customer_observed_asset_count}；CloudAtlas 观测资产：{summary.cloudatlas_observed_asset_count}；匹配资产：{summary.matched_asset_count}；本轮 Finding：{summary.current_run_finding_count}。</p>",
            (
                "<p>所有已观测 IP 身份均匹配。</p>"
                if summary.all_observed_ip_identities_matched
                else "<p>存在未匹配的已观测 IP 身份。</p>"
            ),
            "<ul>",
        ]
    )
    sections.extend(
        f"<li>{_text(item.finding_type)}：{item.count}</li>"
        for item in summary.finding_counts
    )
    sections.extend(
        [
            "</ul>",
            "</section>",
            '<section id="current-run-lifecycle-changes">',
            "<h2>本轮生命周期变化</h2>",
            f"<p>本轮共发生 {changes.total} 个 Finding Transition。</p>",
            "<ul>",
        ]
    )
    sections.extend(
        f"<li>{_text(item.transition_type)}：{item.count}</li>"
        for item in changes.transition_counts
    )
    sections.extend(
        [
            "</ul>",
            "</section>",
            '<section id="open-backlog-as-of-run">',
            "<h2>截至本轮的开放积压</h2>",
            f"<p>截至 GovernanceRun <code>{_text(backlog.as_of_governance_run_id)}</code> 仍 OPEN 的 Finding 共 {backlog.total} 个。</p>",
            "<ul>",
        ]
    )
    sections.extend(
        f"<li>{_text(item.finding_type)}：{item.count}</li>"
        for item in backlog.finding_counts
    )
    sections.extend(
        [
            "</ul>",
            "</section>",
            '<section id="evidence-examples">',
            "<h2>Evidence 示例</h2>",
        ]
    )
    rendered_entries = evidence.entries[:HTML_EVIDENCE_MAX_ENTRIES]
    if not rendered_entries:
        sections.append("<p>无可展示的 Evidence 示例。</p>")
    for index, entry in enumerate(rendered_entries, start=1):
        transition = entry.transition_type or "无本轮 Transition"
        sections.extend(
            [
                f'<article class="evidence-card" id="evidence-card-{index}">',
                f"<h3>Evidence {index}</h3>",
                f"<p>覆盖：{_text(entry.coverage)}</p>",
                f"<p>Finding：<code>{_text(entry.finding_id)}</code></p>",
                f"<p>类型：{_text(entry.finding_type)}；Canonical IP：<code>{_text(entry.canonical_ip)}</code>；Transition：{_text(transition)}</p>",
                f"<p>来源事实：{_text(entry.evidence_reference.fact_type)} / <code>{_text(entry.evidence_reference.fact_id)}</code></p>",
                f'<p><a href="{_text(_evidence_reference(entry))}">查看 Evidence</a> · <a href="{_text(_finding_reference(entry.finding_id, identity.governance_run_id))}">查看 Finding 明细</a></p>',
                "</article>",
            ]
        )
    sections.extend(
        [
            "</section>",
            '<section id="directions-and-limitations">',
            "<h2>Finding 类型处置方向与限制</h2>",
            "<ul>",
        ]
    )
    present_directions = tuple(
        direction
        for direction in report.finding_type_directions_and_limitations.directions
        if direction.present
    )
    if present_directions:
        sections.extend(
            f"<li>{_text(direction.finding_type)}：{_text(direction.direction)}</li>"
            for direction in present_directions
        )
    else:
        sections.append("<li>本报告没有需要处置的 Finding。</li>")
    sections.extend(["</ul>", "<h3>限制</h3>", "<ul>"])
    sections.extend(
        f"<li>{_text(limitation)}</li>"
        for limitation in report.finding_type_directions_and_limitations.limitations
    )
    provenance = report.provenance
    sections.extend(
        [
            "</ul>",
            "</section>",
            '<section id="provenance">',
            "<h2>来源追溯</h2>",
            f"<p>GovernanceRun：<code>{_text(provenance.governance_run_id)}</code>；处理契约：<code>{_text(provenance.processing_contract_version)}</code>；Finding 生命周期事实：{provenance.finding_lifecycle_fact_count}。</p>",
            "<ul>",
        ]
    )
    sections.extend(
        f"<li>Snapshot <code>{_text(snapshot_id)}</code> / SHA-256 <code>{_text(snapshot_hash)}</code></li>"
        for snapshot_id, snapshot_hash in zip(
            provenance.source_snapshot_ids,
            provenance.source_snapshot_hashes,
            strict=True,
        )
    )
    sections.extend(["</ul>", "</section>", "</body>", "</html>", ""])
    return "\n".join(sections).encode("utf-8")


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _safe_csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    stripped = text.lstrip()
    if text and (text[0] in "\t\r\n" or (stripped and stripped[0] in "=+-@")):
        return "'" + text
    return text


def _csv_evidence_index(evidence: EvidenceBundle) -> dict[str, str]:
    return {entry.finding_id: _evidence_reference(entry) for entry in evidence.entries}


def _csv_row(
    report: CanonicalReportCore,
    row: FindingExportRow,
    evidence_references: Mapping[str, str],
) -> tuple[object, ...]:
    identity = report.report_identity
    return (
        identity.report_contract_version,
        identity.governance_run_id,
        row.finding_id,
        row.canonical_ip,
        row.finding_type,
        row.status_as_of_run,
        row.current_run_transition,
        _timestamp(row.first_occurrence_at),
        _timestamp(row.last_occurrence_at),
        row.occurrence_count_as_of_run,
        row.transition_count_as_of_run,
        evidence_references.get(row.finding_id, ""),
        _finding_reference(row.finding_id, identity.governance_run_id),
    )


def _render_csv(report: CanonicalReportCore, evidence: EvidenceBundle) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(tuple(_safe_csv_cell(value) for value in CSV_COLUMNS))
    evidence_references = _csv_evidence_index(evidence)
    for row in sorted(
        report.finding_export_rows,
        key=lambda item: _finding_sort_key(
            item.finding_type, item.canonical_ip, item.finding_id
        ),
    ):
        writer.writerow(
            tuple(
                _safe_csv_cell(value)
                for value in _csv_row(report, row, evidence_references)
            )
        )
    return stream.getvalue().encode("utf-8")


def _hash_outputs(*outputs: bytes) -> tuple[str, ...]:
    try:
        return tuple(hashlib.sha256(output).hexdigest() for output in outputs)
    except Exception:
        raise ReportRendererError("hash_failed") from None


def render_report(
    report_model: CanonicalReportCore | Mapping[str, object],
    evidence_plan: EvidenceBundle | Mapping[str, object],
) -> RenderedReport:
    """Atomically render canonical JSON, HTML, CSV, and their SHA-256 hashes."""

    report, evidence = _validated_inputs(report_model, evidence_plan)
    try:
        canonical_json = _canonical_json(report, evidence)
        html_bytes = _render_html(report, evidence)
        csv_bytes = _render_csv(report, evidence)
    except ReportRendererError:
        raise
    except Exception:
        raise ReportRendererError("render_failed") from None

    canonical_hash, html_hash, csv_hash = _hash_outputs(
        canonical_json, html_bytes, csv_bytes
    )
    return RenderedReport(
        canonical_json=canonical_json,
        html=html_bytes,
        csv=csv_bytes,
        canonical_json_sha256=canonical_hash,
        html_sha256=html_hash,
        csv_sha256=csv_hash,
    )
