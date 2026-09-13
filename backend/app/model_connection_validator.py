"""Fixed non-customer capability checks through the task-only backend proxy."""

from __future__ import annotations

import contextlib
import io
import os
import secrets
import uuid
from collections.abc import Callable
from typing import Any, Literal

from sqlmodel import Session

from app.core.db import engine
from app.domain import model_connections as service
from app.domain.model_connection_proxy import transport_binding
from app.domain.model_qualification import QualificationRunResult
from app.domain.models import ModelConnectionLease, ModelConnectionOperation
from app.integrations.model_connection_runtime import client_for_version
from app.integrations.pi_investigation import run_pi_investigation
from app.model_qualification_runner import (
    _run_qualification,
    _runner_build_version,
    _start_provider_proxy,
)

FIXTURE_CITATION = "model-connection:fixture-v1"


def main() -> int:
    operation_id = uuid.UUID(os.environ.get("MODEL_VALIDATION_OPERATION_ID", ""))
    run_id = os.environ.get("MODEL_VALIDATION_RUN_ID", "")
    sandbox = os.environ.get("SANDBOX_ID", "")
    evidence: dict[str, Any] = {
        "schema": "model-connection-validation-v1",
        "qualification": "NOT_RUN",
        "investigation": "NOT_RUN",
        "analysis_report": "NOT_RUN",
        "runtime": "NOT_RUN",
        "project_data_permission": "NOT_GRANTED",
    }
    try:
        with Session(engine) as session:
            service.state_for_write(session)
            op = session.get(ModelConnectionOperation, operation_id)
            if (
                op is None
                or op.agent_run_id != run_id
                or not sandbox
                or (op.session_id is not None and op.session_id != sandbox)
            ):
                return 1
            if op.status in {"SUCCEEDED", "FAILED"} or (
                op.evidence and op.evidence.get("execution_started")
            ):
                return 0
            binding = service.validation_binding(session, operation_id)
            version = service.get_version(session, op.connection_id)
            if _runner_build_version() != version.runner_build_version:
                raise service.ModelConnectionError("model_binding_changed")
            op.session_id = sandbox
            op.status = "RUNNING"
            evidence.update(
                execution_started=True,
                fingerprint=binding.config_fingerprint,
                operation_id=str(op.id),
                agent_run_id=run_id,
                session_id=sandbox,
                runtime_spec_hash=version.runtime_spec_hash,
            )
            op.evidence = evidence.copy()
            session.add(op)
            session.commit()
            # commit expires ORM state; load the immutable runtime projection
            # before taking it across the process-control boundary.
            session.refresh(version)
            session.expunge(version)
        observed = client_for_version(version).get_run(run_id)
        if observed is None or not observed.is_active or observed.session_id != sandbox:
            raise service.ModelConnectionError("model_connection_runtime_unknown")
        evidence["runtime"] = "PASS"

        def guard() -> None:
            with Session(engine) as session:
                current = service.validation_binding(session, operation_id)
                if current.config_fingerprint != binding.config_fingerprint:
                    raise service.ModelConnectionError("model_binding_changed")

        def checkpoint() -> None:
            with Session(engine) as session:
                op = session.get(ModelConnectionOperation, operation_id)
                if op is not None and op.status not in {"SUCCEEDED", "FAILED"}:
                    op.evidence = evidence.copy()
                    session.add(op)
                    session.commit()

        guard()
        transport, token = transport_binding(binding, "qualification")
        capability = secrets.token_urlsafe(32)
        proxy, thread = _start_provider_proxy(
            transport, capability=capability, upstream_token=token
        )
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                _run_qualification(transport, capability, proxy.server_port)
        finally:
            proxy.shutdown()
            proxy.server_close()
            thread.join()
        parsed = QualificationRunResult.model_validate_json(output.getvalue().strip())
        if (
            parsed.config_fingerprint != binding.config_fingerprint
            or parsed.evaluation().status != "PASS"
        ):
            raise service.ModelConnectionError("model_connection_qualification_failed")
        evidence["qualification"] = "PASS"
        checkpoint()
        purposes: tuple[Literal["investigation", "analysis_report"], ...] = (
            "investigation",
            "analysis_report",
        )
        for purpose in purposes:
            guard()
            transport, token = transport_binding(binding, purpose)

            def material(_: dict[str, Any]) -> dict[str, Any]:
                guard()
                return {
                    "status": "SUCCEEDED",
                    "citation_ids": [FIXTURE_CITATION],
                    "summary": {"synthetic_record_count": 1},
                    "items": [{"citation_id": FIXTURE_CITATION, "synthetic": True}],
                    "gaps": ["Fixed non-customer capability check only."],
                }

            tools: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = (
                {"read_report_material": material}
                if purpose == "analysis_report"
                else {
                    "read_asset_facts": material,
                    "read_asset_history": lambda _: {
                        "status": "SUCCEEDED",
                        "items": [],
                    },
                    "read_cloudatlas_asset": lambda _: {
                        "status": "SUCCEEDED",
                        "items": [],
                    },
                }
            )
            result = run_pi_investigation(
                binding=transport,
                api_key=token,
                tools=tools,
                task=purpose,
                before_model_call=guard,
                timeout_seconds=80,
                max_tool_calls=2,
                max_material_bytes=4096,
                max_output_bytes=8192,
            )
            if purpose == "analysis_report":
                from app.domain.ai_analysis_reports import validate_output
            else:
                from app.domain.ai_investigations import validate_output
            validate_output(
                result, citation_ids={FIXTURE_CITATION}, max_output_bytes=8192
            )
            evidence[purpose] = "PASS"
            checkpoint()
        with Session(engine) as session:
            service.finish_validation(session, operation_id, evidence)
        return 0
    except Exception:
        failure = "model_connection_validation_failed"
        # Error details from providers, configuration, and credentials never leave the supervisor.
        with Session(engine) as session:
            from sqlmodel import select

            leases = session.exec(
                select(ModelConnectionLease).where(
                    ModelConnectionLease.family == "validation",
                    ModelConnectionLease.task_id == operation_id,
                )
            ).all()
            failure = next(
                (lease.failure_code for lease in leases if lease.failure_code), failure
            )
            service.finish_validation(session, operation_id, evidence, failure)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
