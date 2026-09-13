"""Credential-bearing supervisor for isolated, fixed-material Pi analysis reports."""

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
    from app.domain import ai_analysis_reports as service
    from app.domain.ai_investigations import canonical_bytes
    from app.integrations.pi_investigation import run_pi_investigation
    from app.model_qualification_runner import _runner_build_version
except ValueError, OSError:
    sys.stderr.write("AI analysis report runner: configuration_invalid\n")
    raise SystemExit(1) from None


_FAILURE_CODES = frozenset(
    {
        "model_run_failed",
        "model_connection_revoked",
        "model_connection_disabled",
        "model_connection_lease_expired",
        "model_connection_proxy_denied",
        "model_connection_secret_unavailable",
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
        "analysis_report_scope_denied",
        "analysis_report_material_changed",
    }
)


def main() -> int:
    if len(sys.argv) != 1:
        return 1
    try:
        report_id = uuid.UUID(os.environ.get("AI_ANALYSIS_REPORT_ID", ""))
        expected_run_id = os.environ.get("AI_ANALYSIS_REPORT_RUN_ID", "")
        session_id = os.environ.get("SANDBOX_ID", "")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_run_id) or not re.fullmatch(
            r"[0-9a-f]{64}", session_id
        ):
            return 1
        with Session(engine) as session:
            record = service.locked_record(session, report_id)
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
            service.audit(session, record, "analysis_report.started")
            session.commit()
            session.refresh(record)
            session.expunge(record)
    except ValueError, SQLAlchemyError:
        return 1
    started = time.monotonic()
    successful_calls = bytes_read = attempted_calls = 0
    citation_ids: set[str] = set()

    def authorize() -> None:
        service.load_material(
            project_id=record.project_id,
            user_id=record.created_by_id,
            run_id=record.run_id,
            record=record,
        )

    def read_tool(arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal successful_calls, bytes_read, attempted_calls
        attempted_calls += 1
        if arguments != {}:
            raise service.AnalysisReportError("tool_scope_denied")
        if attempted_calls > record.max_tool_calls:
            raise service.AnalysisReportError("tool_call_limit")
        material, _, _ = service.load_material(
            project_id=record.project_id,
            user_id=record.created_by_id,
            run_id=record.run_id,
            record=record,
        )
        size = len(canonical_bytes(material))
        if bytes_read + size > record.max_material_bytes:
            raise service.AnalysisReportError("material_limit")
        if time.monotonic() - started > record.timeout_seconds:
            raise service.AnalysisReportError("investigation_timeout")
        citation_ids.update(item["citation_id"] for item in material["items"])
        successful_calls += 1
        bytes_read += size
        return material

    try:
        if _runner_build_version() != settings.RUNNER_BUILD_VERSION:
            raise service.AnalysisReportError("model_binding_changed")
        _, _, binding = service.load_material(
            project_id=record.project_id,
            user_id=record.created_by_id,
            run_id=record.run_id,
            record=record,
        )
        api_key = settings.MODEL_API_KEY.get_secret_value()
        transport = binding
        if record.connection_version_id is not None:
            from app.domain.model_connection_proxy import transport_binding
            transport, api_key = transport_binding(binding, "analysis_report")
        output = run_pi_investigation(
            binding=transport,
            api_key=api_key,
            tools={"read_report_material": read_tool},
            task="analysis_report",
            before_model_call=authorize,
            timeout_seconds=record.timeout_seconds - (time.monotonic() - started),
            max_tool_calls=record.max_tool_calls,
            max_material_bytes=record.max_material_bytes,
            max_output_bytes=record.max_output_bytes,
        )
        if successful_calls < 1:
            raise service.AnalysisReportError("tool_required")
        if time.monotonic() - started > record.timeout_seconds:
            raise service.AnalysisReportError("investigation_timeout")
        validated = service.validate_output(
            output, citation_ids=citation_ids, max_output_bytes=record.max_output_bytes
        )
        service.finish(
            analysis_report_id=record.id,
            output=validated,
            successful_tool_calls=successful_calls,
            material_bytes_read=bytes_read,
        )
        return 0
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, ValueError) and str(error) in _FAILURE_CODES
            else "model_run_failed"
        )
        try:
            service.finish(
                analysis_report_id=record.id,
                failure_code=code,
                successful_tool_calls=successful_calls,
                material_bytes_read=bytes_read,
            )
        except SQLAlchemyError:
            return 1
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
