"""Strict v2-only comparison references; selection never persists facts."""

import uuid
from collections.abc import Mapping
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.domain.evidence_selector import EvidencePlanEntry
from app.domain.ip_consistency import IPRecordContractError, normalize_ip
from app.domain.ip_source_comparison import (
    COMPARISON_CONTRACT_VERSION,
    IPSourceComparisonError,
    RunIPSourceComparison,
    comparison_fact_id,
    compile_ip_source_comparison,
)


def _canonical_ip(value: str) -> str:
    try:
        canonical = normalize_ip(value)
    except IPRecordContractError:
        raise ValueError("invalid comparison IP") from None
    if canonical != value:
        raise ValueError("comparison IP is not canonical")
    return value


UUIDString = Annotated[
    str,
    Field(
        strict=True,
        min_length=36,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
]
CanonicalIP = Annotated[
    str, Field(strict=True, min_length=2, max_length=39), AfterValidator(_canonical_ip)
]
ContentHash = Annotated[
    str, Field(strict=True, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always"
    )


class ComparisonEvidenceReference(_FrozenModel):
    governance_run_id: UUIDString
    fact_type: Literal["IP_SOURCE_COMPARISON"]
    fact_id: UUIDString
    content_hash: ContentHash


class ComparisonEvidencePlanEntry(_FrozenModel):
    coverage: Literal["IP_SOURCE_COMPARISON"]
    resource_id: UUIDString
    canonical_ip: CanonicalIP
    evidence_reference: ComparisonEvidenceReference

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        reference = self.evidence_reference
        if reference.fact_id != str(
            comparison_fact_id(
                uuid.UUID(reference.governance_run_id), self.canonical_ip
            )
        ):
            raise ValueError("comparison reference identity differs")
        return self


class ReportV2EvidenceBundle(_FrozenModel):
    governance_run_id: UUIDString
    report_contract_version: Literal["deterministic-report-v2"]
    max_entries: Literal[100]
    entries: Annotated[tuple[EvidencePlanEntry, ...], Field(max_length=50)]
    comparison_entries: Annotated[
        tuple[ComparisonEvidencePlanEntry, ...], Field(max_length=50)
    ]

    @model_validator(mode="before")
    @classmethod
    def validate_budget_type(cls, data: object) -> object:
        if isinstance(data, Mapping) and type(data.get("max_entries")) is not int:
            raise ValueError("comparison budget must be an integer")
        return data

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        references: set[tuple[str, str]] = set()
        resources: set[str] = set()
        entries: tuple[EvidencePlanEntry | ComparisonEvidencePlanEntry, ...] = (
            *self.entries,
            *self.comparison_entries,
        )
        for entry in entries:
            reference = entry.evidence_reference
            key = (reference.fact_type, reference.fact_id)
            if (
                reference.governance_run_id != self.governance_run_id
                or key in references
            ):
                raise ValueError("duplicate or out-of-scope evidence reference")
            references.add(key)
            if isinstance(entry, ComparisonEvidencePlanEntry):
                if entry.resource_id in resources:
                    raise ValueError("duplicate comparison resource")
                resources.add(entry.resource_id)
        return self


def validate_comparison(
    comparison: RunIPSourceComparison, *, netflow_present: bool
) -> None:
    """Recompile every row using the sole comparison implementation before slicing."""
    if comparison.contract_version != COMPARISON_CONTRACT_VERSION:
        raise IPSourceComparisonError("comparison_contract_unsupported")
    rows = comparison.results
    resources = {row.resource_id: row.canonical_ip for row in rows}
    if len(resources) != len(rows):
        raise ValueError("duplicate resource")
    if any(
        type(value) is not bool
        for row in rows
        for value in (row.customer_upload_present, row.cloudatlas_present)
    ):
        raise ValueError("comparison presence must be boolean")
    memberships = {
        row.resource_id: {
            source
            for source, present in (
                ("CUSTOMER_UPLOAD", row.customer_upload_present),
                ("CLOUDATLAS", row.cloudatlas_present),
            )
            if present
        }
        for row in rows
    }
    expected = compile_ip_source_comparison(
        tenant_id=comparison.tenant_id,
        project_id=comparison.project_id,
        run_id=comparison.governance_run_id,
        resources=resources,
        membership=memberships,
        active_resources={
            row.resource_id for row in rows if row.netflow_status == "ACTIVE"
        },
        netflow_present=netflow_present,
    )
    if expected != comparison:
        raise ValueError("comparison content, order or hash differs")


def select_comparison_evidence(
    comparison: RunIPSourceComparison,
) -> tuple[ComparisonEvidencePlanEntry, ...]:
    # Empty/all-active results have no absent/present ambiguity in their hash.
    validate_comparison(
        comparison,
        netflow_present=not any(
            row.netflow_reason == "netflow_input_absent" for row in comparison.results
        ),
    )
    return tuple(
        ComparisonEvidencePlanEntry(
            coverage="IP_SOURCE_COMPARISON",
            resource_id=str(row.resource_id),
            canonical_ip=row.canonical_ip,
            evidence_reference=ComparisonEvidenceReference(
                governance_run_id=str(comparison.governance_run_id),
                fact_type="IP_SOURCE_COMPARISON",
                fact_id=str(
                    comparison_fact_id(comparison.governance_run_id, row.canonical_ip)
                ),
                content_hash=row.content_hash,
            ),
        )
        for row in comparison.results[:50]
    )


def comparison_evidence_id(
    report_id: uuid.UUID, index: int, fact_id: uuid.UUID
) -> uuid.UUID:
    if type(index) is not int or not 0 <= index < 50:
        raise ValueError("comparison evidence index outside selection")
    return uuid.uuid5(report_id, f"{index}:IP_SOURCE_COMPARISON:{fact_id}")
