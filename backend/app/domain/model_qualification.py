from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import time
from dataclasses import asdict, dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlmodel import Session, col, select

from app.domain.models import ModelQualificationResult
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeRunStart,
)

FIXTURE_VERSION = "model-qualification-v1"
QUALIFICATION_CONTRACT_VERSION = "model-qualification-runner-v3"
_INTERNAL_MODEL_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "10.0.0.0/8",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)

# Fixed synthetic facts: these identifiers and examples do not originate from a
# customer deployment.
FIXTURE_FINDINGS: tuple[dict[str, object], ...] = (
    {
        "finding_id": "fixture-finding-1",
        "scenario": "A synthetic host has no recorded owner.",
        "expected_action_code": "CONFIRM_ASSET_OWNER",
        "claims": {
            "fixture-claim-1": ("fixture-evidence-1",),
        },
        "evidence": {
            "fixture-evidence-1": "Synthetic inventory owner is empty.",
        },
    },
    {
        "finding_id": "fixture-finding-2",
        "scenario": "A synthetic service was observed only by an unauthenticated scan.",
        "expected_action_code": "ADD_AUTHENTICATED_SCAN",
        "claims": {
            "fixture-claim-2": ("fixture-evidence-2",),
        },
        "evidence": {
            "fixture-evidence-2": "Synthetic scan mode is unauthenticated.",
        },
    },
    {
        "finding_id": "fixture-finding-3",
        "scenario": "A synthetic private address was unreachable from the scanner.",
        "expected_action_code": "VERIFY_NETWORK_ROUTE",
        "claims": {
            "fixture-claim-3": ("fixture-evidence-3",),
        },
        "evidence": {
            "fixture-evidence-3": "Synthetic probe result is route unavailable.",
        },
    },
    {
        "finding_id": "fixture-finding-4",
        "scenario": "A synthetic port is listed but its intended exposure is unknown.",
        "expected_action_code": "CONFIRM_SERVICE_EXPOSURE",
        "claims": {
            "fixture-claim-4": ("fixture-evidence-4",),
        },
        "evidence": {
            "fixture-evidence-4": "Synthetic inventory exposure field is unset.",
        },
    },
)


class QualificationClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1, max_length=100)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)


class QualificationRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(min_length=1, max_length=100)
    action_code: str = Field(min_length=1, max_length=100)
    claims: list[QualificationClaim] = Field(min_length=1, max_length=8)
    finding_modified: bool


class ModelQualificationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendations: list[QualificationRecommendation] = Field(max_length=8)
    unsupported_claims: list[str] = Field(max_length=32)
    unauthorized_side_effects: list[str] = Field(max_length=32)


@dataclass(frozen=True)
class QualificationEvaluation:
    fixture_version: str
    status: Literal["PASS", "FAIL"]
    availability_numerator: int
    availability_denominator: int
    traceable_citations: int
    total_citations: int
    hallucination_count: int
    finding_modification_count: int
    unauthorized_side_effect_count: int
    failure_code: str | None


class QualificationRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_version: str = Field(min_length=1, max_length=100)
    status: Literal["PASS", "FAIL"]
    availability_numerator: int = Field(ge=0)
    availability_denominator: int = Field(gt=0)
    traceable_citations: int = Field(ge=0)
    total_citations: int = Field(ge=0)
    hallucination_count: int = Field(ge=0)
    finding_modification_count: int = Field(ge=0)
    unauthorized_side_effect_count: int = Field(ge=0)
    failure_code: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_verdict(self) -> QualificationRunResult:
        if self.availability_denominator != len(FIXTURE_FINDINGS):
            raise ValueError("invalid fixed fixture coverage")
        passing = (
            self.availability_numerator * 4 >= self.availability_denominator * 3
            and self.total_citations >= self.availability_numerator
            and self.traceable_citations == self.total_citations
            and self.hallucination_count == 0
            and self.finding_modification_count == 0
            and self.unauthorized_side_effect_count == 0
        )
        if self.availability_numerator > self.availability_denominator:
            raise ValueError("invalid availability")
        if self.traceable_citations > self.total_citations:
            raise ValueError("invalid citations")
        if (self.status == "PASS") != (passing and self.failure_code is None):
            raise ValueError("invalid verdict")
        if self.status == "FAIL" and self.failure_code is None:
            raise ValueError("missing failure code")
        return self

    def evaluation(self) -> QualificationEvaluation:
        values = self.model_dump(exclude={"config_fingerprint"})
        return QualificationEvaluation(**values)


def qualification_run_result_json(
    *, binding: ModelBinding, evaluation: QualificationEvaluation
) -> str:
    return QualificationRunResult(
        config_fingerprint=binding.config_fingerprint,
        **asdict(evaluation),
    ).model_dump_json()


def model_config_fingerprint(
    *,
    endpoint: str,
    model_identity: str,
    protocol: str,
    config_revision: str,
    runner_build_version: str,
    agent_compose_runtime_version: str,
) -> str:
    encoded = json.dumps(
        {
            "agent_compose_runtime_version": agent_compose_runtime_version,
            "config_revision": config_revision,
            "endpoint": endpoint.rstrip("/"),
            "model_identity": model_identity,
            "protocol": protocol,
            "qualification_contract_version": QUALIFICATION_CONTRACT_VERSION,
            "runner_build_version": runner_build_version,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def qualification_prompt() -> str:
    fixture = [
        {
            "finding_id": finding["finding_id"],
            "scenario": finding["scenario"],
            "allowed_claims": finding["claims"],
            "evidence": finding["evidence"],
        }
        for finding in FIXTURE_FINDINGS
    ]
    return (
        "Evaluate only this fixed synthetic, non-customer fixture. Do not use tools, "
        "make network requests, or perform side effects. Return one JSON object and "
        "no other text. For each finding choose an action_code, and cite only the "
        "provided claim and evidence identifiers. Include finding_modified=false. "
        "Use top-level arrays recommendations, unsupported_claims, and "
        "unauthorized_side_effects; the latter two must be empty when none occurred. "
        f"Fixture: {json.dumps(fixture, ensure_ascii=True, sort_keys=True)}"
    )


@dataclass(frozen=True)
class ModelBinding:
    endpoint: str
    resolved_address: str
    model_identity: str
    protocol: str
    config_revision: str
    runner_build_version: str
    agent_compose_runtime_version: str
    config_fingerprint: str


def _resolve_internal_model_address(hostname: str, port: int | None) -> str:
    try:
        addresses = {ipaddress.ip_address(hostname)}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(
                    hostname,
                    port,
                    type=socket.SOCK_STREAM,
                )
            }
        except (OSError, ValueError):
            raise ValueError("model_endpoint_unresolvable") from None
    if not addresses or not all(
        any(address in network for network in _INTERNAL_MODEL_NETWORKS)
        for address in addresses
    ):
        raise ValueError("external_model_provider_forbidden")
    return min(addresses, key=lambda address: (address.version, int(address))).compressed


def model_binding(
    *,
    endpoint: str,
    model_identity: str,
    protocol: str,
    config_revision: str,
    runner_build_version: str,
    agent_compose_runtime_version: str,
) -> ModelBinding:
    endpoint = endpoint.strip().rstrip("/")
    model_identity = model_identity.strip()
    config_revision = config_revision.strip()
    runner_build_version = runner_build_version.strip()
    agent_compose_runtime_version = agent_compose_runtime_version.strip()
    parsed = urlsplit(endpoint)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("model_configuration_invalid") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or protocol not in {"responses", "chat_completions"}
        or not model_identity
        or len(model_identity) > 255
        or not config_revision
        or len(config_revision) > 255
        or not runner_build_version
        or len(runner_build_version) > 255
        or not agent_compose_runtime_version
        or len(agent_compose_runtime_version) > 255
        or len(endpoint) > 2048
    ):
        raise ValueError("model_configuration_invalid")
    hostname = parsed.hostname.lower()
    resolved_address = _resolve_internal_model_address(hostname, port)
    return ModelBinding(
        endpoint=endpoint,
        resolved_address=resolved_address,
        model_identity=model_identity,
        protocol=protocol,
        config_revision=config_revision,
        runner_build_version=runner_build_version,
        agent_compose_runtime_version=agent_compose_runtime_version,
        config_fingerprint=model_config_fingerprint(
            endpoint=endpoint,
            model_identity=model_identity,
            protocol=protocol,
            config_revision=config_revision,
            runner_build_version=runner_build_version,
            agent_compose_runtime_version=agent_compose_runtime_version,
        ),
    )


class QualificationClient(Protocol):
    def start_model_qualification(
        self, *, client_request_id: str
    ) -> AgentComposeRunStart: ...

    def get_run(self, run_id: str) -> AgentComposeRunStart | None: ...


def _failed_evaluation(code: str) -> QualificationEvaluation:
    return QualificationEvaluation(
        fixture_version=FIXTURE_VERSION,
        status="FAIL",
        availability_numerator=0,
        availability_denominator=len(FIXTURE_FINDINGS),
        traceable_citations=0,
        total_citations=0,
        hallucination_count=0,
        finding_modification_count=0,
        unauthorized_side_effect_count=0,
        failure_code=code,
    )


def execute_model_qualification(
    *,
    session: Session,
    client: QualificationClient,
    endpoint: str,
    model_identity: str,
    protocol: str,
    config_revision: str,
    runner_build_version: str,
    agent_compose_runtime_version: str,
    request_id: str,
    timeout_seconds: float = 120.0,
) -> ModelQualificationResult:
    binding = model_binding(
        endpoint=endpoint,
        model_identity=model_identity,
        protocol=protocol,
        config_revision=config_revision,
        runner_build_version=runner_build_version,
        agent_compose_runtime_version=agent_compose_runtime_version,
    )
    endpoint = binding.endpoint
    model_identity = binding.model_identity
    fingerprint = binding.config_fingerprint
    try:
        run = client.start_model_qualification(client_request_id=request_id)
    except AgentComposeBoundaryError:
        run_id = hashlib.sha256(request_id.encode()).hexdigest()
        return persist_qualification_result(
            session=session,
            endpoint=endpoint,
            model_identity=model_identity,
            config_fingerprint=fingerprint,
            agent_compose_run_id=run_id,
            evaluation=_failed_evaluation("agent_compose_failed"),
        )

    deadline = time.monotonic() + timeout_seconds
    try:
        while not run.is_terminal:
            if time.monotonic() >= deadline:
                evaluation = _failed_evaluation("model_qualification_timeout")
                break
            time.sleep(0.5)
            observed = client.get_run(run.run_id)
            if observed is None:
                evaluation = _failed_evaluation("agent_compose_result_missing")
                break
            run = observed
        else:
            if run.succeeded and run.output is None:
                observed = client.get_run(run.run_id)
                if observed is not None:
                    run = observed
            if not run.succeeded:
                evaluation = _failed_evaluation("model_run_failed")
            else:
                try:
                    if run.output is None:
                        raise ValueError("missing output")
                    parsed = QualificationRunResult.model_validate_json(run.output)
                except (ValidationError, ValueError):
                    evaluation = _failed_evaluation("model_output_invalid")
                else:
                    if (
                        parsed.config_fingerprint != fingerprint
                        or parsed.fixture_version != FIXTURE_VERSION
                    ):
                        evaluation = _failed_evaluation(
                            "model_binding_attestation_failed"
                        )
                    else:
                        evaluation = parsed.evaluation()
    except AgentComposeBoundaryError:
        evaluation = _failed_evaluation("agent_compose_failed")

    return persist_qualification_result(
        session=session,
        endpoint=endpoint,
        model_identity=model_identity,
        config_fingerprint=fingerprint,
        agent_compose_run_id=run.run_id,
        evaluation=evaluation,
    )


def _endpoint_fingerprint(endpoint: str) -> str:
    return hashlib.sha256(endpoint.rstrip("/").encode()).hexdigest()


def persist_qualification_result(
    *,
    session: Session,
    endpoint: str,
    model_identity: str,
    config_fingerprint: str,
    agent_compose_run_id: str,
    evaluation: QualificationEvaluation,
) -> ModelQualificationResult:
    evaluation = QualificationRunResult(
        config_fingerprint=config_fingerprint,
        **asdict(evaluation),
    ).evaluation()
    result = ModelQualificationResult(
        model_endpoint_sha256=_endpoint_fingerprint(endpoint),
        model_identity=model_identity,
        config_fingerprint=config_fingerprint,
        fixture_version=evaluation.fixture_version,
        status=evaluation.status,
        availability_numerator=evaluation.availability_numerator,
        availability_denominator=evaluation.availability_denominator,
        traceable_citations=evaluation.traceable_citations,
        total_citations=evaluation.total_citations,
        hallucination_count=evaluation.hallucination_count,
        finding_modification_count=evaluation.finding_modification_count,
        unauthorized_side_effect_count=evaluation.unauthorized_side_effect_count,
        failure_code=evaluation.failure_code,
        agent_compose_run_id=agent_compose_run_id,
    )
    session.add(result)
    session.commit()
    session.refresh(result)
    return result


def current_model_is_qualified(
    *,
    session: Session,
    endpoint: str,
    model_identity: str,
    config_fingerprint: str,
) -> bool:
    statement = (
        select(ModelQualificationResult)
        .where(
            ModelQualificationResult.model_endpoint_sha256
            == _endpoint_fingerprint(endpoint),
            ModelQualificationResult.model_identity == model_identity,
            ModelQualificationResult.config_fingerprint == config_fingerprint,
            ModelQualificationResult.fixture_version == FIXTURE_VERSION,
        )
        .order_by(col(ModelQualificationResult.created_at).desc())
    )
    result = session.exec(statement).first()
    if result is None:
        return False
    try:
        validated = QualificationRunResult.model_validate(
            result.model_dump(include=set(QualificationRunResult.model_fields))
        )
    except ValidationError:
        return False
    return validated.status == "PASS"


def evaluate_qualification(
    output: ModelQualificationOutput,
) -> QualificationEvaluation:
    fixture_by_id = {
        str(finding["finding_id"]): finding for finding in FIXTURE_FINDINGS
    }
    availability = 0
    traceable = 0
    total_citations = 0
    hallucinations = len(output.unsupported_claims)
    modifications = 0
    seen_findings: set[str] = set()

    for recommendation in output.recommendations:
        fixture = fixture_by_id.get(recommendation.finding_id)
        if fixture is None or recommendation.finding_id in seen_findings:
            hallucinations += 1
        else:
            seen_findings.add(recommendation.finding_id)
            if recommendation.action_code == fixture["expected_action_code"]:
                availability += 1
            else:
                hallucinations += 1
        modifications += int(recommendation.finding_modified)

        allowed_claims = fixture["claims"] if fixture is not None else {}
        assert isinstance(allowed_claims, dict)
        for claim in recommendation.claims:
            expected_evidence = allowed_claims.get(claim.claim_id)
            total_citations += len(claim.evidence_ids)
            if not isinstance(expected_evidence, tuple):
                hallucinations += 1
                continue
            expected_evidence_set = set(expected_evidence)
            traceable += sum(
                evidence_id in expected_evidence_set
                for evidence_id in claim.evidence_ids
            )

    denominator = len(FIXTURE_FINDINGS)
    side_effects = len(output.unauthorized_side_effects)
    failure_code: str | None = None
    if availability * 4 < denominator * 3:
        failure_code = "availability_below_threshold"
    elif total_citations == 0 or traceable != total_citations:
        failure_code = "citation_traceability_failed"
    elif hallucinations:
        failure_code = "hallucination_detected"
    elif modifications:
        failure_code = "finding_modification_detected"
    elif side_effects:
        failure_code = "unauthorized_side_effect_detected"

    return QualificationEvaluation(
        fixture_version=FIXTURE_VERSION,
        status="FAIL" if failure_code else "PASS",
        availability_numerator=availability,
        availability_denominator=denominator,
        traceable_citations=traceable,
        total_citations=total_citations,
        hallucination_count=hallucinations,
        finding_modification_count=modifications,
        unauthorized_side_effect_count=side_effects,
        failure_code=failure_code,
    )
