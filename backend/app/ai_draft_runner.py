"""Draft-ID-only runner entry that reloads bounded input from PostgreSQL."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.domain.ai_governance_drafts import (
    AiDraftModelOutput,
    AiGovernanceDraftStateError,
    DraftRunnerHandoff,
    DraftRunnerInputs,
    bind_draft_session,
    fail_draft,
    load_draft_runner_inputs,
    mark_draft_reviewable,
)
from app.domain.model_qualification import (
    ModelBinding,
    current_model_is_qualified,
    model_binding,
)
from app.domain.models import AiGovernanceDraft
from app.model_qualification_runner import (
    start_pinned_provider_proxy,
    stop_pinned_provider_proxy,
)

logger = logging.getLogger(__name__)


def _stop(code: str) -> int:
    logger.error(
        "AI governance draft runner stopped: %s",
        code,
        extra={"ai_draft_runner_error_code": code},
    )
    return 1


def _inputs_json(inputs: DraftRunnerInputs) -> str:
    return json.dumps(asdict(inputs), default=str, sort_keys=True)


def _model_prompt(inputs: DraftRunnerInputs) -> str:
    """Serialize the frozen, minimal model contract without deployment secrets."""
    return json.dumps(
        {
            "instruction": (
                "Produce one non-authoritative AI governance draft. Return exactly "
                "one JSON object matching output_contract and no other text. Do not "
                "use tools, make external writes, invent factual identities, or "
                "change Findings. Cite only the Evidence IDs allowlisted for each "
                "Finding."
            ),
            "report": {"sha256": inputs.report_sha256},
            "findings": [
                {
                    "finding_id": str(finding.finding_id),
                    "finding_type": finding.finding_type,
                    "canonical_ip": finding.canonical_ip,
                    "coverage": finding.coverage,
                    "transition_type": finding.transition_type,
                    "allowed_evidence": [
                        {
                            "evidence_id": str(evidence.id),
                            "fact_type": evidence.fact_type,
                            "fact_id": str(evidence.fact_id),
                        }
                        for evidence in finding.evidence
                    ],
                }
                for finding in inputs.findings
            ],
            "output_contract": {
                "report_sha256": "64 lowercase hexadecimal characters",
                "summary": "non-empty text",
                "recommendations": [
                    {
                        "finding_id": "one selected Finding ID, exactly once",
                        "rescan_recommendation": "non-empty text",
                        "pending_verifications": ["text"],
                        "limitations": ["text"],
                        "claims": [
                            {
                                "claim_id": "non-empty identifier",
                                "evidence_ids": [
                                    "the allowlisted Evidence ID for this Finding"
                                ],
                            }
                        ],
                    }
                ],
            },
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _current_qualified_binding(
    *, session: Session, inputs: DraftRunnerInputs
) -> ModelBinding:
    """Recompute the complete binding immediately before model egress."""
    if not settings.MODEL_API_KEY.get_secret_value():
        raise AiGovernanceDraftStateError("model_binding_changed")
    try:
        binding = model_binding(
            endpoint=settings.MODEL_API_ENDPOINT,
            model_identity=settings.MODEL_IDENTITY,
            protocol=settings.MODEL_API_PROTOCOL,
            config_revision=settings.MODEL_CONFIG_REVISION,
            runner_build_version=settings.RUNNER_BUILD_VERSION,
            agent_compose_runtime_version=settings.AGENT_COMPOSE_RUNTIME_VERSION,
        )
    except ValueError:
        raise AiGovernanceDraftStateError("model_binding_changed") from None
    if (
        binding.model_identity != inputs.model_identity
        or binding.config_fingerprint != inputs.config_fingerprint
        or not current_model_is_qualified(
            session=session,
            endpoint=binding.endpoint,
            model_identity=binding.model_identity,
            config_fingerprint=binding.config_fingerprint,
        )
    ):
        raise AiGovernanceDraftStateError("model_binding_changed")
    return binding


def _model_configuration(
    *, binding: ModelBinding, proxy_port: int, directory: Path
) -> Path:
    """Write Pi configuration whose Provider base URL is loopback-only."""
    configuration = directory / "agent"
    configuration.mkdir()
    (configuration / "settings.json").write_text(
        '{"retry":{"enabled":false,"provider":{"maxRetries":0}}}',
        encoding="utf-8",
    )
    (configuration / "models.json").write_text(
        json.dumps(
            {
                "providers": {
                    "customer": {
                        # The qualified endpoint is reachable only through the
                        # deployment-local pinned proxy. Never use binding.endpoint.
                        "baseUrl": f"http://127.0.0.1:{proxy_port}",
                        "api": (
                            "openai-responses"
                            if binding.protocol == "responses"
                            else "openai-completions"
                        ),
                        "apiKey": "$MODEL_API_KEY",
                        "models": [{"id": binding.model_identity}],
                    }
                }
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return configuration


def _run_model(
    *, binding: ModelBinding, inputs: DraftRunnerInputs, proxy_port: int
) -> AiDraftModelOutput:
    """Make the single bounded Pi attempt with no inherited application capability."""
    with tempfile.TemporaryDirectory(prefix="ai-governance-draft-") as temporary:
        working_directory = Path(temporary)
        configuration = _model_configuration(
            binding=binding,
            proxy_port=proxy_port,
            directory=working_directory,
        )
        environment = {
            "HOME": temporary,
            "LANG": "C.UTF-8",
            "MODEL_API_KEY": settings.MODEL_API_KEY.get_secret_value(),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PI_CODING_AGENT_DIR": str(configuration),
            "PI_OFFLINE": "1",
            "PI_SKIP_VERSION_CHECK": "1",
            "PI_TELEMETRY": "0",
        }
        try:
            completed = subprocess.run(
                [
                    "pi",
                    "--print",
                    "--no-session",
                    "--no-tools",
                    "--no-extensions",
                    "--no-skills",
                    "--no-prompt-templates",
                    "--no-themes",
                    "--no-context-files",
                    "--no-approve",
                    "--provider",
                    "customer",
                    "--model",
                    binding.model_identity,
                ],
                cwd=temporary,
                env=environment,
                input=_model_prompt(inputs),
                capture_output=True,
                text=True,
                timeout=settings.MODEL_QUALIFICATION_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise AiGovernanceDraftStateError("model_run_failed") from None
    if completed.returncode != 0:
        raise AiGovernanceDraftStateError("model_run_failed")
    if (
        not completed.stdout.strip()
        or len(completed.stdout.encode("utf-8")) > 1_000_000
    ):
        raise AiGovernanceDraftStateError("model_output_invalid")
    try:
        return AiDraftModelOutput.model_validate_json(completed.stdout)
    except ValueError:
        raise AiGovernanceDraftStateError("model_output_invalid") from None


def _persist_failure(*, handoff: DraftRunnerHandoff, code: str) -> None:
    """Persist one redacted terminal when a started generation cannot succeed."""
    try:
        with Session(engine) as session:
            draft = session.get(AiGovernanceDraft, handoff.draft_id)
            if draft is not None:
                fail_draft(
                    session=session,
                    draft=draft,
                    failure_code=code,
                    agent_compose_run_id=handoff.agent_compose_run_id,
                    session_id=handoff.session_id,
                )
    except (AiGovernanceDraftStateError, SQLAlchemyError):
        # Keep terminal persistence diagnostics out of lifecycle output.
        return


def main() -> int:
    if len(sys.argv) != 1:
        return _stop("runner_handoff_invalid")
    try:
        handoff = DraftRunnerHandoff.from_environment(
            {
                "AI_DRAFT_ID": os.environ.get("AI_DRAFT_ID", ""),
                "AI_DRAFT_RUN_ID": os.environ.get("AI_DRAFT_RUN_ID", ""),
                "SANDBOX_ID": os.environ.get("SANDBOX_ID", ""),
            }
        )
    except AiGovernanceDraftStateError as error:
        return _stop(error.code)
    try:
        with Session(engine) as session:
            draft = session.get(AiGovernanceDraft, handoff.draft_id)
            if draft is None:
                raise AiGovernanceDraftStateError("draft_not_found")
            bound = bind_draft_session(
                session=session,
                draft=draft,
                agent_compose_run_id=handoff.agent_compose_run_id,
                session_id=handoff.session_id,
            )
            inputs = load_draft_runner_inputs(
                session=session,
                draft_id=bound.id,
                session_id=handoff.session_id,
            )
            # Release database locks before the one external Provider attempt.
            session.commit()
    except AiGovernanceDraftStateError as error:
        _persist_failure(handoff=handoff, code=error.code)
        return _stop(error.code)
    except SQLAlchemyError:
        return _stop("storage_unavailable")
    try:
        with Session(engine) as session:
            binding = _current_qualified_binding(session=session, inputs=inputs)
            session.commit()
        # A proxy is mandatory: Pi can only reach the pinned loopback listener.
        proxy, proxy_thread = start_pinned_provider_proxy(binding)
        try:
            output = _run_model(
                binding=binding,
                inputs=inputs,
                proxy_port=proxy.server_port,
            )
        finally:
            stop_pinned_provider_proxy(proxy, proxy_thread)
        with Session(engine) as session:
            draft = session.get(AiGovernanceDraft, handoff.draft_id)
            if draft is None:
                raise AiGovernanceDraftStateError("draft_not_found")
            mark_draft_reviewable(session=session, draft=draft, model_output=output)
    except AiGovernanceDraftStateError as error:
        _persist_failure(handoff=handoff, code=error.code)
        return _stop(error.code)
    except SQLAlchemyError:
        _persist_failure(handoff=handoff, code="storage_unavailable")
        return _stop("storage_unavailable")
    except OSError:
        _persist_failure(handoff=handoff, code="model_run_failed")
        return _stop("model_run_failed")
    logger.info("AI governance draft generation completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
