"""Trusted supervisor: only this process receives database and model credentials."""

from __future__ import annotations

import os
import re
import sys
import time
import uuid
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

try:
    from app.core.config import settings
    from app.core.db import engine
    from app.core.time import get_datetime_utc
    from app.domain import ai_investigations as service
    from app.integrations.pi_investigation import run_pi_investigation
    from app.model_qualification_runner import _runner_build_version
except ValueError, OSError:
    # Settings validation can contain credential-bearing input; never emit it.
    sys.stderr.write("AI investigation runner: configuration_invalid\n")
    raise SystemExit(1) from None

_FAILURE_CODES = frozenset(
    {
        "model_run_failed",
        "model_output_invalid",
        "tool_required",
        "tool_scope_denied",
        "tool_failed",
        "tool_call_limit",
        "material_limit",
        "output_limit",
        "investigation_timeout",
        "model_citation_invalid",
        "model_not_qualified",
        "model_binding_changed",
        "synthetic_material_denied",
        "synthetic_manifest_invalid",
        "investigation_scope_denied",
        "investigation_material_invalid",
        "investigation_material_changed",
        "investigation_finding_not_in_run",
        "investigation_material_truncated",
    }
)


def main() -> int:
    if len(sys.argv) != 1:
        return 1
    try:
        investigation_id = uuid.UUID(os.environ.get("AI_INVESTIGATION_ID", ""))
        expected_run_id = os.environ.get("AI_INVESTIGATION_RUN_ID", "")
        session_id = os.environ.get("SANDBOX_ID", "")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_run_id) or not re.fullmatch(
            r"[0-9a-f]{64}", session_id
        ):
            return 1
        with Session(engine) as session:
            record = service.locked_record(session, investigation_id)
            if record.agent_compose_run_id != expected_run_id or (
                record.session_id is not None and record.session_id != session_id
            ):
                return 1
            if record.status != "GENERATING" or record.execution_started_at is not None:
                return 0
            record.session_id = session_id
            record.execution_started_at = get_datetime_utc()
            record.failure_code = None
            session.add(record)
            service.audit(session, record, "ai_investigation.started")
            session.commit()
            session.refresh(record)
            session.expunge(record)
    except ValueError, SQLAlchemyError:
        return 1

    started = time.monotonic()
    successful_calls = 0
    bytes_read = 0
    attempted_calls = 0
    citation_ids: set[str] = set()
    scope = service.InvestigationRequest(
        resource_id=record.resource_id,
        run_id=record.run_id,
        finding_id=record.finding_id,
    )

    def read_facts(arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal successful_calls, bytes_read, attempted_calls
        attempted_calls += 1
        if arguments != {}:
            raise service.InvestigationError("tool_scope_denied")
        if attempted_calls > record.max_tool_calls:
            raise service.InvestigationError("tool_call_limit")
        material, _sources, _binding = service.load_material(
            project_id=record.project_id,
            user_id=record.initiated_by,
            scope=scope,
            record=record,
        )
        size = len(service.canonical_bytes(material))
        if bytes_read + size > record.max_material_bytes:
            raise service.InvestigationError("material_limit")
        if time.monotonic() - started > record.timeout_seconds:
            raise service.InvestigationError("investigation_timeout")
        bytes_read += size
        successful_calls += 1
        citation_ids.update(item["citation_id"] for item in material["items"])
        return material

    try:
        if _runner_build_version() != settings.RUNNER_BUILD_VERSION:
            raise service.InvestigationError("model_binding_changed")
        _material, _sources, binding = service.load_material(
            project_id=record.project_id,
            user_id=record.initiated_by,
            scope=scope,
            record=record,
        )
        remaining = record.timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise service.InvestigationError("investigation_timeout")
        output = run_pi_investigation(
            binding=binding,
            api_key=settings.MODEL_API_KEY.get_secret_value(),
            read_facts=read_facts,
            timeout_seconds=remaining,
            max_tool_calls=record.max_tool_calls,
            max_material_bytes=record.max_material_bytes,
            max_output_bytes=record.max_output_bytes,
        )
        if successful_calls < 1:
            raise service.InvestigationError("tool_required")
        if time.monotonic() - started > record.timeout_seconds:
            raise service.InvestigationError("investigation_timeout")
        validated = service.validate_output(
            output, citation_ids=citation_ids, max_output_bytes=record.max_output_bytes
        )
        service.finish(
            investigation_id=record.id,
            output=validated,
            successful_tool_calls=successful_calls,
            material_bytes_read=bytes_read,
        )
        return 0
    except Exception as error:
        # Never print provider text, prompts, model output, or credential-bearing exceptions.
        code = (
            str(error)
            if isinstance(error, ValueError) and str(error) in _FAILURE_CODES
            else "model_run_failed"
        )
        try:
            service.finish(
                investigation_id=record.id,
                failure_code=code,
                successful_tool_calls=successful_calls,
                material_bytes_read=bytes_read,
            )
        except SQLAlchemyError:
            return 1
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
