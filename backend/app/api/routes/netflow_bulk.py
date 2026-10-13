"""Controlled server-side admission. HTTP never transports or parses bulk files."""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.netflow_http import NetFlowRoute
from app.core.time import get_datetime_utc
from app.domain import netflow_bulk as bulk
from app.domain import netflow_bulk_queries as queries
from app.domain import netflow_processing as legacy
from app.domain.netflow_bulk_models import BulkDataset, BulkJob, BulkMember
from app.domain.netflow_common import deny, project_for
from app.netflow_bulk.contracts import BulkError


class BulkRoute(NetFlowRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def bounded(request: Request) -> Response:
            received = 0

            async def receive() -> dict[str, Any]:
                nonlocal received
                message = await request.receive()
                received += len(message.get("body", b""))
                if received > 2 * 1024 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail={"code": "bulk_request_limit"},
                        headers={"Cache-Control": "private, no-store"},
                    )
                return message

            return await handler(Request(request.scope, receive=receive))

        return bounded


router = APIRouter(
    prefix="/projects/{project_id}/netflow-bulk",
    tags=["netflow-bulk"],
    route_class=BulkRoute,
)
Key = Annotated[str, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9_-]{1,128}$")]


class Registered(BaseModel):
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    source_id: str
    ready_id: str
    file_count: int
    byte_size: int
    counts_state: str


@router.post("/datasets", response_model=Registered, status_code=201)
def register(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    body: bulk.Register,
    idempotency_key: Key,
) -> Registered:
    project = project_for(session, current_user, project_id, write=True, admin=True)
    try:
        dataset = bulk.register(session, project, current_user, body, idempotency_key)
    except (BulkError, OSError, ValueError) as error:
        deny(
            error.code if isinstance(error, BulkError) else "bulk_input_not_found", 422
        )
    info = session.get(BulkDataset, dataset.id)
    assert info is not None
    return Registered(
        project_id=project.id,
        dataset_id=dataset.id,
        source_id=info.source_id,
        ready_id=info.ready_id,
        file_count=len(info.manifest["files"]),
        byte_size=dataset.byte_size,
        counts_state="NORMALIZED" if info.complete else "PENDING",
    )


@router.post(
    "/datasets/{dataset_id}/analyses",
    response_model=legacy.AnalysisPublic,
    status_code=202,
)
def analyze(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    body: bulk.Analyze,
    idempotency_key: Key,
) -> legacy.AnalysisPublic:
    project = project_for(session, current_user, project_id, write=True)
    row, created = bulk.reserve(
        session, project, current_user, dataset_id, body, idempotency_key
    )
    if created:
        row = legacy.launch_analysis(session, row)
    return legacy.analysis_public(session, project, row)


@router.get("/analyses/{analysis_id}/progress")
def progress(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
    response: Response,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    project = project_for(session, current_user, project_id)
    row = legacy.analysis_for(session, project, analysis_id)
    legacy.validate_context(
        session,
        project,
        legacy.context_for(session, project, row.dataset_id, row.context_revision_id),
    )
    job = session.get(BulkJob, row.id)
    if job is None:
        deny("netflow_analysis_not_found", 404)
    members = session.exec(
        select(BulkMember).where(BulkMember.dataset_id == row.dataset_id)
    ).all()
    return queries.identity(row) | {
        "status": row.status,
        "phase": job.phase,
        "cancel_requested": job.cancel_requested,
        "heartbeat_at": job.heartbeat_at,
        "lease_until": job.lease_until,
        "files_completed": sum(m.complete for m in members),
        "files_total": len(members),
        "rows_normalized": sum(m.raw_count for m in members),
        "metrics": job.metrics,
    }


@router.post("/analyses/{analysis_id}/cancel")
def cancel(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
) -> dict[str, Any]:
    project = project_for(session, current_user, project_id, write=True)
    row = legacy.analysis_for(session, project, analysis_id)
    job = bulk._job(session, row.id)
    if row.status in legacy.UNFINISHED:
        job.cancel_requested = True
        if job.lease_until is None:
            job.phase = "CANCELLED"
            row.status, row.error_code, row.completed_at = (
                "FAILED",
                "bulk_cancelled",
                get_datetime_utc(),
            )
            session.add(row)
        session.add(job)
        session.commit()
    return {"analysis_id": analysis_id, "cancel_requested": job.cancel_requested}


@router.get("/analyses/{analysis_id}/record")
def record(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
    response: Response,
    reference: Annotated[str, Query(max_length=128)],
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    project = project_for(session, current_user, project_id)
    return queries.record(session, project, analysis_id, reference)


@router.post("/analyses/{analysis_id}/invalidate")
def invalidate(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
) -> dict[str, Any]:
    project = project_for(session, current_user, project_id, write=True, admin=True)
    bulk.invalidate(session, project, current_user, analysis_id)
    return {"analysis_id": analysis_id, "invalidated": True}
