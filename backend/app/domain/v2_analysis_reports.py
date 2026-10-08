"""Fixed V2 report contracts and bounded reader adaptation; no model statistics."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from itertools import zip_longest
from typing import Annotated, Any, Literal, Never

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlmodel import Session

from app.api.project_authorization import PROJECT_READ_ROLES, get_authorized_project
from app.core.db import engine
from app.core.time import get_datetime_utc
from app.domain import comparison_results as core
from app.domain.ai_investigations import canonical_bytes, material_hash
from app.domain.comparison_models import CoreComparisonSupplement
from app.domain.models import AnalysisReport, Project
from app.models import User

MATERIAL_VERSION = "v2-ai-material-v1"
OUTPUT_VERSION = "v2-ai-output-v1"
REPORT_SECTIONS = (
    "conclusion",
    "differences",
    "priority",
    "netflow",
    "next_steps",
    "appendix",
)
ADDRESS_SECTIONS = (
    "known_facts",
    "possible_explanations",
    "missing_evidence",
    "next_checks",
)
Text = Annotated[
    str,
    StringConstraints(
        strict=True, strip_whitespace=True, min_length=1, max_length=2000
    ),
]
Ref = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]
ClaimId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
]
AddressKey = Annotated[
    str, StringConstraints(strict=True, pattern=r"^addr:[a-f0-9]{64}$")
]


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_kind: Literal["core_comparison_v2"] = "core_comparison_v2"
    result_id: uuid.UUID
    supplement_binding_id: uuid.UUID | None = Field(...)
    audience: Literal["management", "operations"] = "management"
    language: Literal["zh", "en"] = "zh"
    address_key: AddressKey | None = None


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["CUSTOMER", "CLOUD", "NETFLOW"]
    version_id: str
    domain: str
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SyntheticPermission(Request):
    subject_kind: Literal["core_comparison_v2"] = Field(...)
    project_id: uuid.UUID
    core_input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    binding_revision: int | None
    valid_until: datetime | None
    material_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sources: list[Source] = Field(min_length=2)


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["counts", "address", "identity", "source_record", "supplement"]
    value: dict[str, Any]
    evidence_refs: list[Ref] = Field(min_length=1)


class Material(BaseModel):
    model_config = ConfigDict(extra="forbid")
    captured_at: datetime
    subject: dict[str, Any]
    identity: dict[str, Any]
    summary: dict[str, Any]
    facts: dict[str, Fact]
    items: list[dict[str, Any]]
    samples: list[dict[str, Any]]
    coverage: dict[str, Any]
    limitations: list[str]


class FactClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: ClaimId
    type: Literal["fact"]
    fact_refs: list[Ref] = Field(min_length=1, max_length=8)
    evidence_refs: list[Ref] = Field(min_length=1, max_length=8)


class NarrativeClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: ClaimId
    type: Literal["explanation", "hypothesis", "gap", "action"]
    text: Text
    fact_refs: list[Ref] = Field(default_factory=list, max_length=8)
    evidence_refs: list[Ref] = Field(min_length=1, max_length=8)


Claim = Annotated[FactClaim | NarrativeClaim, Field(discriminator="type")]


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Literal[
        "conclusion",
        "differences",
        "priority",
        "netflow",
        "next_steps",
        "appendix",
        "known_facts",
        "possible_explanations",
        "missing_evidence",
        "next_checks",
    ]
    claim_ids: list[ClaimId] = Field(min_length=1, max_length=16)


class PriorityCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address_key: AddressKey
    why_review: Text
    next_check: Text
    evidence_refs: list[Ref] = Field(min_length=1, max_length=8)


class ReportText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: list[ClaimId] = Field(min_length=1, max_length=8)
    sections: list[Section] = Field(min_length=4, max_length=6)
    claims: list[Claim] = Field(min_length=1, max_length=48)
    priority_cases: list[PriorityCase] = Field(max_length=20)
    limitations: list[Text] = Field(max_length=32)


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["v2-ai-output-v1"]
    text: ReportText


class Update(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(strict=True, ge=1)
    edits: dict[ClaimId, Text] = Field(max_length=48)
    case_edits: dict[AddressKey, dict[Literal["why_review", "next_check"], Text]] = (
        Field(default_factory=dict, max_length=20)
    )


class Public(Request):
    id: uuid.UUID
    project_id: uuid.UUID
    status: Literal["GENERATING", "DRAFT", "CONFIRMED", "FAILED"]
    revision: int
    created_at: datetime
    completed_at: datetime | None
    edited_at: datetime | None
    confirmed_at: datetime | None
    created_by_id: uuid.UUID
    edited_by_id: uuid.UUID | None
    confirmed_by_id: uuid.UUID | None
    connection_version_id: uuid.UUID | None
    config_fingerprint: str
    material_sha256: str
    failure_code: str | None
    readable: bool
    unavailable_reason: str | None
    materials_changed: bool | None
    valid_until: datetime | None
    original_output: Output | None
    text: ReportText | None
    material: Material | None


class Listing(BaseModel):
    data: list[Public]
    count: int
    can_create: bool


class Readiness(BaseModel):
    project_id: uuid.UUID
    result_id: uuid.UUID
    supplement_binding_id: uuid.UUID | None
    state: Literal[
        "READY",
        "NO_PERMISSION",
        "NOT_CONFIGURED",
        "NOT_ENABLED",
        "NOT_QUALIFIED",
        "MATERIAL_UNAVAILABLE",
        "MODEL_UNAVAILABLE",
    ]
    can_create: bool
    reason_code: str | None = None
    connection_version_id: uuid.UUID | None = None


def deny(code: str) -> Never:
    # The shared error is imported only at call time to keep the adapter acyclic.
    from app.domain.ai_analysis_reports import AnalysisReportError

    raise AnalysisReportError(code)


def request_for(record: AnalysisReport) -> Request:
    return Request.model_validate(
        {
            "result_id": record.core_result_id,
            "supplement_binding_id": record.supplement_binding_id,
            "audience": record.audience,
            "language": record.language,
            "address_key": record.address_key,
        }
    )


def subject(project_id: uuid.UUID, request: Request) -> dict[str, Any]:
    return {
        **request.model_dump(mode="json"),
        "project_id": str(project_id),
        "material_contract_version": MATERIAL_VERSION,
        "template_version": "v2-ai-address-v1"
        if request.address_key
        else "v2-ai-report-v1",
    }


def read_scope(session: Session, project: Project, request: Request) -> Any:
    try:
        result = core._result(session, project, request.result_id)
        core._read(session, project, result)
        if request.address_key:
            core.address_detail(session, project, result.id, request.address_key)
        if request.supplement_binding_id:
            binding = session.get(
                CoreComparisonSupplement, request.supplement_binding_id
            )
            if binding is None or (
                binding.result_id,
                binding.project_id,
                binding.tenant_id,
            ) != (result.id, project.id, project.tenant_id):
                deny("v2_report_material_unavailable")
            core._binding_material(session, project, result, binding)
        return result
    except HTTPException as error:
        deny(
            "v2_report_material_expired"
            if error.status_code == 410
            else "v2_report_material_unavailable"
        )


def check_record(session: Session, project: Project, record: AnalysisReport) -> None:
    request = request_for(record)
    result = read_scope(session, project, request)
    if (
        record.subject_kind != "core_comparison_v2"
        or record.project_id != project.id
        or record.tenant_id != project.tenant_id
        or record.request_sha256 != material_hash(request.model_dump(mode="json"))
        or record.material_sha256
        != material_hash(
            {
                key: value
                for key, value in record.material.items()
                if key != "captured_at"
            }
        )
        or record.material.get("subject") != subject(project.id, request)
        or record.material.get("identity", {}).get("input_sha256")
        != result.input_sha256
    ):
        deny("v2_report_material_invalid")


def prepare_material(
    session: Session, project: Project, request: Request, max_bytes: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result = read_scope(session, project, request)
    summary = core.summary(session, project, result.id).model_dump(mode="json")
    loaded, values, comparison = core._addresses(session, project, result)
    entries = [
        core._address(value, comparison.state == "AVAILABLE") for value in values
    ]
    if request.address_key:
        entries = [
            entry for entry in entries if entry.address_key == request.address_key
        ]
    groups = [
        [entry for entry in entries if entry.classification == kind]
        for kind in ("cloud_only", "customer_only", "both", None)
    ]
    selected = [
        entry for row in zip_longest(*groups) for entry in row if entry is not None
    ][:20]
    base_ref = f"core:{result.id}"
    facts: dict[str, Any] = {
        f"fact:{result.id}:counts": {
            "kind": "counts",
            "value": {
                key: summary[key]
                for key in (
                    "total_addresses",
                    "both",
                    "cloud_only",
                    "customer_only",
                    "comparison_state",
                )
            },
            "evidence_refs": [base_ref],
        },
        f"fact:{result.id}:identity": {
            "kind": "identity",
            "value": {
                key: summary[key]
                for key in (
                    "id",
                    "published_at",
                    "customer_applied_at",
                    "selection",
                    "rule_version",
                )
            },
            "evidence_refs": [base_ref],
        },
    }
    items: list[dict[str, Any]] = [
        {
            "citation_id": base_ref,
            "kind": "CORE_RESULT",
            "identity": str(result.id),
            "data": {"input_sha256": result.input_sha256},
        }
    ]
    samples: list[dict[str, Any]] = []
    record_omissions = 0
    customer_fields = (
        "asset_ip",
        "start_port",
        "end_port",
        "is_web",
        "web_url",
        "service_type",
        "asset_owner",
        "asset_department",
        "port_owner",
        "department",
        "serial",
    )
    cloud_fields = (
        "ip",
        "port",
        "protocol",
        "service",
        "product",
        "version",
        "status",
        "bu",
        "tags",
        "created_at",
        "updated_at",
        "lastseen_at",
    )
    for entry in selected:
        ref = f"address:{result.id}:{entry.address_key}"
        data = entry.model_dump(mode="json")
        facts[f"fact:{result.id}:{entry.address_key}"] = {
            "kind": "address",
            "value": data,
            "evidence_refs": [ref],
        }
        items.append(
            {
                "citation_id": ref,
                "kind": "ADDRESS",
                "identity": entry.address_key,
                "data": data,
            }
        )
        sample = {**data, "evidence_refs": [ref], "source_refs": []}
        for source_name in ("CUSTOMER", "CLOUD"):
            records = [
                record
                for record in loaded[source_name].records
                if record.canonical_ip == entry.canonical_ip
            ]
            kept = []
            for domain in dict.fromkeys(record.domain for record in records):
                domain_records = [
                    record for record in records if record.domain == domain
                ]
                kept.extend(domain_records[:2])
                record_omissions += max(0, len(domain_records) - 2)
            for record in kept:
                identity = {
                    "result_id": str(result.id),
                    "source": source_name,
                    "version_id": record.version_id,
                    "domain": record.domain,
                    "record_key": record.record_key,
                }
                source_ref = f"source:{result.id}:{hashlib.sha256(canonical_bytes(identity)).hexdigest()}"
                original = (
                    record.original.get("fields", {})
                    if source_name == "CUSTOMER"
                    else record.original
                )
                fields = customer_fields if source_name == "CUSTOMER" else cloud_fields
                projection = {key: original[key] for key in fields if key in original}
                items.append(
                    {
                        "citation_id": source_ref,
                        "kind": "SOURCE_RECORD",
                        "identity": identity,
                        "data": projection,
                    }
                )
                facts[f"fact:{source_ref}"] = {
                    "kind": "source_record",
                    "value": {"source_ref": source_ref},
                    "evidence_refs": [source_ref],
                }
                sample["source_refs"].append(source_ref)
        samples.append(sample)
    sources = [
        Source(
            kind="CUSTOMER",
            version_id=str(
                result.pins["CUSTOMER"].get("revision_id")
                or result.pins["CUSTOMER"]["upload_id"]
            ),
            domain="customer",
            content_sha256=result.pins["CUSTOMER"]["rows_sha256"],
        ).model_dump(mode="json"),
        *[
            Source(
                kind="CLOUD",
                version_id=str(pin["id"]),
                domain=domain,
                content_sha256=pin["records_sha256"],
            ).model_dump(mode="json")
            for domain, pin in result.pins["CLOUD"]["domains"].items()
        ],
    ]
    limitations = [
        "Statistics describe the fixed C+A result; a shared IP does not prove ownership or absence of risk.",
        "Not observed in this batch does not prove an asset is offline; discrepancies are not confirmed vulnerabilities or violations.",
        "Only the selected bounded samples are interpreted. Suggested checks are not completed remediation.",
    ]
    if comparison.state != "AVAILABLE":
        limitations.append(
            "Coverage does not support full-scope difference counts. Missing counts remain unknown."
        )
    if request.supplement_binding_id:
        binding = session.get(CoreComparisonSupplement, request.supplement_binding_id)
        assert binding is not None
        metadata = core.supplement(session, project, result.id, binding.id).model_dump(
            mode="json"
        )
        if metadata["state"] != "ACTIVE":
            deny("v2_report_material_unavailable")
        observations = core.supplement_addresses(
            session,
            project,
            result.id,
            binding.id,
            ips=[entry.canonical_ip for entry in selected],
            only_supplemental=False,
            skip=0,
            limit=20,
        )
        supplement_ref = f"supplement:{binding.id}:v{binding.revision}"
        items.append(
            {
                "citation_id": supplement_ref,
                "kind": "SUPPLEMENT",
                "identity": str(binding.id),
                "data": metadata,
            }
        )
        facts[f"fact:{result.id}:supplement"] = {
            "kind": "supplement",
            "value": {
                "binding": metadata,
                "addresses": [row.model_dump(mode="json") for row in observations.data],
            },
            "evidence_refs": [supplement_ref],
        }
        analysis, _bundle = core._binding_material(session, project, result, binding)
        sources.append(
            Source(
                kind="NETFLOW",
                version_id=str(analysis.id),
                domain="source_observations",
                content_sha256=analysis.processing_identity_sha256,
            ).model_dump(mode="json")
        )
        limitations.append(
            "The actual observation window is unknown unless explicitly provided by the fixed sealed source. Upload, processing and binding times do not prove recent or simultaneous activity."
        )
    else:
        limitations.append(
            "No NetFlow supplement was selected; the C+A core remains independently readable."
        )
    if request.language == "zh":
        translations = {
            "Statistics describe the fixed C+A result; a shared IP does not prove ownership or absence of risk.": "统计只描述固定的客户与云图资料；同一 IP 不证明资产归属或无风险。",
            "Not observed in this batch does not prove an asset is offline; discrepancies are not confirmed vulnerabilities or violations.": "本批未观测不证明资产已下线；资料差异不是已确认的漏洞或违规。",
            "Only the selected bounded samples are interpreted. Suggested checks are not completed remediation.": "解读仅覆盖所选有界样本；建议核实不表示已完成处置。",
            "Coverage does not support full-scope difference counts. Missing counts remain unknown.": "资料覆盖不足以支持全范围差异计数；缺失的计数保持未知。",
            "The actual observation window is unknown unless explicitly provided by the fixed sealed source. Upload, processing and binding times do not prove recent or simultaneous activity.": "固定封存来源未明确提供实际观测窗口时，窗口保持未知；上传、处理及绑定时间不证明最近或同时活动。",
            "No NetFlow supplement was selected; the C+A core remains independently readable.": "本报告明确未使用 NetFlow 辅证；客户与云图核心独立可读。",
        }
        limitations = [translations[limit] for limit in limitations]
    material: dict[str, Any] = {
        "captured_at": get_datetime_utc().isoformat(),
        "subject": subject(project.id, request),
        "identity": {
            "result_id": str(result.id),
            "input_sha256": result.input_sha256,
            "scope_key": result.scope_key,
            "scope_confirmation_id": str(result.scope_confirmation_id),
            "pins": result.pins,
        },
        "summary": {
            key: summary[key]
            for key in (
                "total_addresses",
                "both",
                "cloud_only",
                "customer_only",
                "comparison_state",
                "sources",
            )
        },
        "facts": facts,
        "items": items,
        "samples": samples,
        "coverage": {
            "eligible_addresses": len(entries),
            "sampled_addresses": len(samples),
            "omitted_addresses": len(entries) - len(samples),
            "omitted_source_records": record_omissions,
            "stop_reason": "address_limit" if len(entries) > len(samples) else "none",
        },
        "limitations": limitations,
    }
    while (
        len(canonical_bytes(material)) > max_bytes
        and samples
        and not request.address_key
    ):
        removed = samples.pop()
        refs = {*removed["evidence_refs"], *removed["source_refs"]}
        items[:] = [item for item in items if item["citation_id"] not in refs]
        for key in [
            key for key, fact in facts.items() if set(fact["evidence_refs"]) & refs
        ]:
            del facts[key]
        supplement = facts.get(f"fact:{result.id}:supplement")
        if supplement:
            supplement["value"]["addresses"] = [
                row
                for row in supplement["value"]["addresses"]
                if row["canonical_ip"] != removed["canonical_ip"]
            ]
        material["coverage"].update(
            sampled_addresses=len(samples),
            omitted_addresses=len(entries) - len(samples),
            stop_reason="material_bytes",
        )
        material["coverage"]["omitted_source_records"] += len(removed["source_refs"])
    # Mandatory aggregates and the selected dependency cannot be silently dropped.
    if len(canonical_bytes(material)) > max_bytes:
        deny("material_limit")
    return Material.model_validate(material).model_dump(mode="json"), sources


# These checks reject the covered unsupported claims; free prose still needs review.
UNSUPPORTED = re.compile(
    r"\d|漏洞|违规|严重|高危|中危|低危|高风险|零风险|已处置|已修复|最近|近.*小时|同时活动|正在运行|监听服务|已证实|vulnerab|violation|sever|zero risk|high risk|critical|medium risk|remediat|resolved|recent|last\s+.*hour|simultaneous|is running|listening|confirmed",
    re.I,
)


def check_prose(text: str) -> None:
    if UNSUPPORTED.search(text):
        deny("v2_report_unsupported_claim")


def validate_output(
    output: dict[str, Any],
    material: dict[str, Any],
    citation_ids: set[str],
    max_output_bytes: int,
) -> dict[str, Any]:
    if len(canonical_bytes(output)) > max_output_bytes:
        deny("output_limit")
    try:
        parsed = Output.model_validate(output)
    except ValueError, TypeError:
        deny("model_output_invalid")
    claims = {claim.id: claim for claim in parsed.text.claims}
    if len(claims) != len(parsed.text.claims):
        deny("model_output_invalid")
    sections = (
        ADDRESS_SECTIONS if material["subject"]["address_key"] else REPORT_SECTIONS
    )
    if tuple(section.id for section in parsed.text.sections) != sections:
        deny("model_output_invalid")
    pointers = [
        *parsed.text.summary,
        *(key for section in parsed.text.sections for key in section.claim_ids),
    ]
    if not set(pointers).issubset(claims):
        deny("model_output_invalid")
    referenced_facts = {
        ref for claim in parsed.text.claims for ref in claim.fact_refs
    }
    required_facts = {f"fact:{material['subject']['result_id']}:counts"}
    if material["subject"]["address_key"]:
        required_facts.add(
            f"fact:{material['subject']['result_id']}:{material['subject']['address_key']}"
        )
    if not required_facts.issubset(referenced_facts):
        deny("model_output_invalid")
    for claim in parsed.text.claims:
        if not set(claim.fact_refs).issubset(material["facts"]) or not set(
            claim.evidence_refs
        ).issubset(citation_ids):
            deny("model_citation_invalid")
        required = {
            ref
            for key in claim.fact_refs
            for ref in material["facts"][key]["evidence_refs"]
        }
        if not required.issubset(claim.evidence_refs):
            deny("model_citation_invalid")
        if isinstance(claim, NarrativeClaim):
            check_prose(claim.text)
    cases = {sample["address_key"]: sample for sample in material["samples"]}
    seen: set[str] = set()
    for case in parsed.text.priority_cases:
        if (
            case.address_key not in cases
            or case.address_key in seen
            or not set(case.evidence_refs).issubset(citation_ids)
            or not set(cases[case.address_key]["evidence_refs"]).issubset(
                case.evidence_refs
            )
        ):
            deny("model_citation_invalid")
        seen.add(case.address_key)
        check_prose(case.why_review)
        check_prose(case.next_check)
    for limit in parsed.text.limitations:
        check_prose(limit)
    if len(parsed.text.limitations) > 24:
        deny("model_output_invalid")
    result = parsed.model_dump(mode="json")
    result["text"]["limitations"] = list(
        dict.fromkeys([*material["limitations"], *result["text"]["limitations"]])
    )
    if len(canonical_bytes(result)) > max_output_bytes:
        deny("output_limit")
    return result


def edit_text(record: AnalysisReport, update: Update) -> dict[str, Any]:
    text = ReportText.model_validate(record.text)
    claims = {claim.id: claim for claim in text.claims}
    for key, value in update.edits.items():
        claim = claims.get(key)
        if not isinstance(claim, NarrativeClaim):
            deny("v2_report_fact_edit_denied")
        check_prose(value)
        claim.text = value
    cases = {case.address_key: case for case in text.priority_cases}
    for key, changes in update.case_edits.items():
        if key not in cases:
            deny("v2_report_fact_edit_denied")
        for field, value in changes.items():
            check_prose(value)
            setattr(cases[key], field, value)
    return text.model_dump(mode="json")


def public(
    record: AnalysisReport, actor: User, *, include_content: bool = True
) -> Public:
    from app.domain.ai_analysis_reports import AnalysisReportError

    readable, reason, changed = True, None, None
    with Session(engine) as session:
        current_actor = session.get(User, actor.id)
        if current_actor is None or not current_actor.is_active:
            raise HTTPException(status_code=404, detail="Report not found")
        project = get_authorized_project(
            session=session,
            user=current_actor,
            project_id=record.project_id,
            allowed_roles=PROJECT_READ_ROLES,
        )
        try:
            check_record(session, project, record)
        except AnalysisReportError as error:
            readable, reason = False, error.code
        if readable:
            try:
                selection = record.material["facts"][
                    f"fact:{record.core_result_id}:identity"
                ]["value"]["selection"]
                ready = core.readiness(
                    session,
                    project,
                    current_actor,
                    source_instance_id=uuid.UUID(
                        record.material["identity"]["pins"]["CLOUD"][
                            "source_instance_id"
                        ]
                    ),
                    network_namespace=selection["network_namespace"],
                )
                if ready.input_sha256 is not None:
                    changed = (
                        ready.input_sha256
                        != record.material["identity"]["input_sha256"]
                    )
            except HTTPException:
                pass  # Current-input failure does not rewrite this fixed report.
    return Public.model_validate(
        {
            **request_for(record).model_dump(),
            **record.model_dump(
                include={
                    "id",
                    "project_id",
                    "status",
                    "revision",
                    "created_at",
                    "completed_at",
                    "edited_at",
                    "confirmed_at",
                    "created_by_id",
                    "edited_by_id",
                    "confirmed_by_id",
                    "connection_version_id",
                    "config_fingerprint",
                    "material_sha256",
                    "failure_code",
                }
            ),
            "readable": readable,
            "unavailable_reason": reason,
            "materials_changed": changed,
            "valid_until": (
                record.material["facts"]
                .get(f"fact:{record.core_result_id}:supplement", {})
                .get("value", {})
                .get("binding", {})
                .get("valid_until")
            ),
            "original_output": record.original_output
            if readable and include_content
            else None,
            "text": record.text if readable and include_content else None,
            "material": record.material if readable and include_content else None,
        }
    )
