"""Bounded AI governance draft runner with fail-closed terminal persistence."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Final

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
from app.model_qualification_runner import _runner_build_version, _start_provider_proxy

logger = logging.getLogger(__name__)

_MAX_MODEL_OUTPUT_BYTES: Final = 1_000_000


def _stop(code: str) -> int:
    logger.error(
        "AI governance draft runner stopped: %s",
        code,
        extra={"ai_draft_runner_error_code": code},
    )
    return 1


def _terminal_output(*, draft_id: object, status: str) -> None:
    sys.stdout.write(
        json.dumps(
            {"draft_id": str(draft_id), "status": status},
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def _generation_prompt(inputs: DraftRunnerInputs) -> str:
    bounded_input = {
        "report_sha256": inputs.report_sha256,
        "findings": [
            {
                "finding_id": str(finding.finding_id),
                "finding_type": finding.finding_type,
                "canonical_ip": finding.canonical_ip,
                "coverage": finding.coverage,
                "transition_type": finding.transition_type,
                "evidence": [
                    {
                        "evidence_id": str(reference.id),
                        "fact_type": reference.fact_type,
                        "fact_id": str(reference.fact_id),
                    }
                    for reference in finding.evidence
                ],
            }
            for finding in inputs.findings
        ],
    }
    contract = AiDraftModelOutput.model_json_schema()
    return (
        "Create one non-authoritative governance recommendation draft from only "
        "the bounded input below. Do not use tools, make side effects, infer new "
        "authoritative facts, or alter any identity. Return exactly one JSON object "
        "and no other text. Copy report_sha256 and every finding_id exactly. Cover "
        "every selected finding exactly once. Every claim must cite only that "
        "finding's supplied evidence_id. Put operational advice in "
        "rescan_recommendation, unknowns in pending_verifications, and constraints "
        "in limitations.\n"
        f"Bounded input: {json.dumps(bounded_input, ensure_ascii=True, sort_keys=True)}\n"
        f"Output JSON Schema: {json.dumps(contract, ensure_ascii=True, sort_keys=True)}"
    )


def _current_binding(
    *, session: Session, inputs: DraftRunnerInputs
) -> tuple[ModelBinding | None, str | None]:
    try:
        if not settings.MODEL_API_KEY.get_secret_value():
            raise ValueError("model_configuration_invalid")
        binding = model_binding(
            endpoint=settings.MODEL_API_ENDPOINT,
            model_identity=settings.MODEL_IDENTITY,
            protocol=settings.MODEL_API_PROTOCOL,
            config_revision=settings.MODEL_CONFIG_REVISION,
            runner_build_version=_runner_build_version(),
            agent_compose_runtime_version=settings.AGENT_COMPOSE_RUNTIME_VERSION,
        )
    except (OSError, ValueError):
        return None, "model_binding_changed"
    if (
        binding.model_identity != inputs.model_identity
        or binding.config_fingerprint != inputs.config_fingerprint
    ):
        return None, "model_binding_changed"
    if not current_model_is_qualified(
        session=session,
        endpoint=binding.endpoint,
        model_identity=binding.model_identity,
        config_fingerprint=binding.config_fingerprint,
    ):
        return None, "model_binding_changed"
    return binding, None


def _run_model(
    *, inputs: DraftRunnerInputs, binding: ModelBinding
) -> tuple[AiDraftModelOutput | None, str | None]:
    api_key = settings.MODEL_API_KEY.get_secret_value()
    try:
        proxy, proxy_thread = _start_provider_proxy(binding)
    except OSError:
        return None, "model_transport_failed"
    completed: subprocess.CompletedProcess[str]
    try:
        with tempfile.TemporaryDirectory(prefix="ai-governance-draft-") as temporary:
            config_dir = Path(temporary) / "agent"
            config_dir.mkdir()
            (config_dir / "settings.json").write_text(
                '{"retry":{"enabled":false,"provider":{"maxRetries":0}}}',
                encoding="utf-8",
            )
            protocol = binding.protocol
            model_identity = binding.model_identity
            (config_dir / "models.json").write_text(
                json.dumps(
                    {
                        "providers": {
                            "customer": {
                                "baseUrl": f"http://127.0.0.1:{proxy.server_port}",
                                "api": (
                                    "openai-responses"
                                    if protocol == "responses"
                                    else "openai-completions"
                                ),
                                "apiKey": "$MODEL_API_KEY",
                                "models": [{"id": model_identity}],
                            }
                        }
                    },
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            environment = {
                "HOME": temporary,
                "LANG": "C.UTF-8",
                "MODEL_API_KEY": api_key,
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PI_CODING_AGENT_DIR": str(config_dir),
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
                        model_identity,
                    ],
                    cwd=temporary,
                    env=environment,
                    input=_generation_prompt(inputs),
                    capture_output=True,
                    text=True,
                    timeout=settings.AI_GOVERNANCE_DRAFT_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                return None, "model_timeout"
            except (OSError, ValueError):
                return None, "model_run_failed"
    finally:
        proxy.shutdown()
        proxy.server_close()
        proxy_thread.join()

    if completed.returncode:
        return None, "model_run_failed"
    output_text = completed.stdout.strip()
    if not output_text:
        return None, "model_output_empty"
    if len(output_text.encode("utf-8")) > _MAX_MODEL_OUTPUT_BYTES:
        return None, "model_output_oversize"
    try:
        return AiDraftModelOutput.model_validate_json(output_text), None
    except ValueError:
        return None, "model_output_invalid"


def _load_inputs_and_binding(
    handoff: DraftRunnerHandoff,
) -> tuple[DraftRunnerInputs | None, ModelBinding | None, str | None]:
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
            binding, failure_code = _current_binding(session=session, inputs=inputs)
            session.commit()
            return inputs, binding, failure_code
    except AiGovernanceDraftStateError as error:
        return None, None, error.code
    except SQLAlchemyError:
        return None, None, "storage_unavailable"


def _persist_failure(*, handoff: DraftRunnerHandoff, failure_code: str) -> bool:
    try:
        with Session(engine) as session:
            draft = session.get(AiGovernanceDraft, handoff.draft_id)
            if draft is None:
                return False
            failed = fail_draft(
                session=session,
                draft=draft,
                failure_code=failure_code,
                agent_compose_run_id=handoff.agent_compose_run_id,
                session_id=handoff.session_id,
            )
            _terminal_output(draft_id=failed.id, status=failed.status)
            return True
    except (AiGovernanceDraftStateError, SQLAlchemyError):
        return False


def _persist_success(
    *, handoff: DraftRunnerHandoff, model_output: AiDraftModelOutput
) -> tuple[bool, str | None]:
    try:
        with Session(engine) as session:
            draft = session.get(AiGovernanceDraft, handoff.draft_id)
            if draft is None:
                return False, "draft_not_found"
            completed = mark_draft_reviewable(
                session=session,
                draft=draft,
                model_output=model_output,
            )
            _terminal_output(draft_id=completed.id, status=completed.status)
            return True, None
    except AiGovernanceDraftStateError as error:
        return False, error.code
    except SQLAlchemyError:
        return False, "storage_unavailable"


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

    inputs, binding, failure_code = _load_inputs_and_binding(handoff)
    if failure_code is not None:
        if failure_code == "storage_unavailable":
            return _stop(failure_code)
        if _persist_failure(handoff=handoff, failure_code=failure_code):
            return 0
        return _stop("terminal_persistence_failed")
    if inputs is None or binding is None:
        return _stop("runner_state_invalid")

    model_output, failure_code = _run_model(inputs=inputs, binding=binding)
    if failure_code is not None:
        if _persist_failure(handoff=handoff, failure_code=failure_code):
            return 0
        return _stop("terminal_persistence_failed")
    assert model_output is not None
    persisted, semantic_failure = _persist_success(
        handoff=handoff,
        model_output=model_output,
    )
    if persisted:
        logger.info(
            "AI governance draft generation completed",
            extra={"ai_draft_id": str(handoff.draft_id)},
        )
        return 0
    if semantic_failure is not None and semantic_failure != "storage_unavailable":
        if _persist_failure(handoff=handoff, failure_code=semantic_failure):
            return 0
    return _stop("terminal_persistence_failed")


if __name__ == "__main__":
    raise SystemExit(main())
