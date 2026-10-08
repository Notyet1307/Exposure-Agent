import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request, Response
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.netflow_http import ERROR_RESPONSES, NetFlowRoute
from app.core.config import settings
from app.domain import netflow_processing as service
from app.domain.models import Artifact, Project
from app.domain.netflow_common import (
    deny,
    new_output_directory,
    operation_result,
    project_for,
)
from app.domain.netflow_models import NetFlowAnalysis, NetFlowContextRevision
from app.domain.netflow_result_imports import receive_result

router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["netflow-processing"],
    route_class=NetFlowRoute,
    responses=ERROR_RESPONSES,
)
Key = Annotated[str, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9_-]{1,128}$")]
Skip = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


@router.get("/netflow-results/current", response_model=service.CurrentNetFlowPublic)
def read_current_netflow(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    response: Response,
    project_id: uuid.UUID,
    collection_scope: str | None = Query(default=None, min_length=1, max_length=128),
) -> service.CurrentNetFlowPublic:
    _private(response)
    project = project_for(session, current_user, project_id)
    return service.current_netflow(session, project, collection_scope)


@router.get(
    "/netflow-datasets/{dataset_id}/processing-contexts",
    response_model=service.ContextPage,
)
def read_contexts(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    response: Response,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    context_revision_id: uuid.UUID | None = None,
    skip: Skip = 0,
    limit: Limit = 25,
) -> service.ContextPage:
    _private(response)
    project = project_for(session, current_user, project_id)
    service.dataset_for(session, project, dataset_id)
    where = [
        NetFlowContextRevision.project_id == project.id,
        NetFlowContextRevision.tenant_id == project.tenant_id,
        NetFlowContextRevision.dataset_id == dataset_id,
    ]
    if context_revision_id is not None:
        where.append(NetFlowContextRevision.id == context_revision_id)
    count = session.exec(
        select(func.count()).select_from(NetFlowContextRevision).where(*where)
    ).one()
    rows = session.exec(
        select(NetFlowContextRevision)
        .where(*where)
        .order_by(
            col(NetFlowContextRevision.created_at).desc(),
            col(NetFlowContextRevision.id),
        )
        .offset(skip)
        .limit(limit)
    ).all()
    return service.ContextPage(
        project_id=project.id,
        dataset_id=dataset_id,
        data=[service.context_public(session, project, row) for row in rows],
        count=count,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/netflow-datasets/{dataset_id}/processing-contexts",
    response_model=service.ContextPublic,
    status_code=201,
)
def create_context(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: service.ContextCreate,
    idempotency_key: Key,
) -> service.ContextPublic:
    project = project_for(session, current_user, project_id, write=True, admin=True)
    row = service.save_context(
        session, project, current_user, dataset_id, request, idempotency_key
    )
    return service.context_public(session, project, row)


@router.get(
    "/netflow-datasets/{dataset_id}/processing-contexts/operations/{key}",
    response_model=service.ContextPublic,
)
def context_operation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    response: Response,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    key: str,
) -> service.ContextPublic:
    _private(response)
    project = project_for(session, current_user, project_id)
    result_id = operation_result(
        session, project, current_user.id, f"context:{dataset_id}", key
    )
    if result_id is None:
        deny("netflow_input_not_found", 404)
    return service.context_public(
        session, project, service.context_for(session, project, dataset_id, result_id)
    )


@router.post(
    "/netflow-datasets/{dataset_id}/analyses",
    response_model=service.AnalysisPublic,
    status_code=202,
)
def create_analysis(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: service.AnalysisCreate,
    idempotency_key: Key,
) -> service.AnalysisPublic:
    project = project_for(session, current_user, project_id, write=True)
    row, created = service.reserve_analysis(
        session, project, current_user, dataset_id, request, idempotency_key
    )
    if created:
        row = service.launch_analysis(session, row)
    return service.analysis_public(session, project, row)


@router.get(
    "/netflow-datasets/{dataset_id}/analyses", response_model=service.AnalysisPage
)
def read_analyses(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    response: Response,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    skip: Skip = 0,
    limit: Limit = 25,
) -> service.AnalysisPage:
    _private(response)
    project = project_for(session, current_user, project_id)
    service.dataset_for(session, project, dataset_id)
    where = (
        NetFlowAnalysis.project_id == project.id,
        NetFlowAnalysis.tenant_id == project.tenant_id,
        NetFlowAnalysis.dataset_id == dataset_id,
    )
    count = session.exec(
        select(func.count()).select_from(NetFlowAnalysis).where(*where)
    ).one()
    rows = session.exec(
        select(NetFlowAnalysis)
        .where(*where)
        .order_by(col(NetFlowAnalysis.created_at).desc(), col(NetFlowAnalysis.id))
        .offset(skip)
        .limit(limit)
    ).all()
    return service.AnalysisPage(
        project_id=project.id,
        dataset_id=dataset_id,
        data=[
            service.analysis_public(session, project, row, include_result=False)
            for row in rows
        ],
        count=count,
        skip=skip,
        limit=limit,
    )


def _analysis_operation(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    kind: str,
    key: str,
) -> service.AnalysisPublic:
    project = project_for(session, current_user, project_id)
    identifier = operation_result(
        session, project, current_user.id, f"{kind}:{dataset_id}", key
    )
    if identifier is None:
        deny("netflow_analysis_not_found", 404)
    return service.analysis_public(
        session, project, service.analysis_for(session, project, identifier)
    )


@router.get(
    "/netflow-datasets/{dataset_id}/analyses/operations/{key}",
    response_model=service.AnalysisPublic,
)
def analysis_operation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    response: Response,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    key: str,
) -> service.AnalysisPublic:
    _private(response)
    return _analysis_operation(
        session, current_user, project_id, dataset_id, "analysis", key
    )


_IMPORT_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["file", "metadata"],
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "metadata": {
                            "type": "string",
                            "contentMediaType": "application/json",
                            "contentSchema": service.ImportMetadata.model_json_schema(),
                        },
                    },
                },
            }
        },
    }
}


@router.post(
    "/netflow-datasets/{dataset_id}/analysis-imports",
    response_model=service.AnalysisPublic,
    status_code=202,
    openapi_extra=_IMPORT_BODY,
)
async def import_analysis(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: Request,
    idempotency_key: Key,
) -> service.AnalysisPublic:
    project = project_for(session, current_user, project_id, write=True, admin=True)
    service.dataset_for(session, project, dataset_id)
    directory = new_output_directory(project.id, "imports")
    created = False
    try:
        upload, metadata = await receive_result(request, directory)
        row, created = service.reserve_analysis(
            session,
            project,
            current_user,
            dataset_id,
            metadata,
            idempotency_key,
            import_directory=directory,
            import_sha256=upload.raw_sha256,
        )
    finally:
        if not created and directory.exists():
            session.rollback()
            # Wait for an uncertain reservation transaction before reading ownership.
            session.exec(
                select(Project.id).where(Project.id == project_id).with_for_update()
            ).one()
            source = directory / "source.zip"
            storage_key = source.relative_to(settings.ARTIFACT_ROOT.resolve()).as_posix()
            # A lost commit acknowledgement may still leave a durable owner.
            owner = session.exec(
                select(Artifact.id).where(Artifact.storage_key == storage_key)
            ).first()
            if owner is None:
                source.unlink(missing_ok=True)
                directory.rmdir()
    if created:
        row = service.launch_analysis(session, row)
    return service.analysis_public(session, project, row)


@router.get(
    "/netflow-datasets/{dataset_id}/analysis-imports/operations/{key}",
    response_model=service.AnalysisPublic,
)
def import_operation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    response: Response,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    key: str,
) -> service.AnalysisPublic:
    _private(response)
    return _analysis_operation(
        session, current_user, project_id, dataset_id, "import", key
    )


@router.get("/netflow-analyses/{analysis_id}", response_model=service.AnalysisPublic)
def read_analysis(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    response: Response,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
) -> service.AnalysisPublic:
    _private(response)
    project = project_for(session, current_user, project_id)
    return service.analysis_public(
        session, project, service.analysis_for(session, project, analysis_id)
    )


@router.post(
    "/netflow-analyses/{analysis_id}/reconcile", response_model=service.AnalysisPublic
)
def reconcile_analysis(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
    idempotency_key: Key,
) -> service.AnalysisPublic:
    project = project_for(session, current_user, project_id, write=True)
    row = service.reconcile_analysis(
        session, project, current_user, analysis_id, idempotency_key
    )
    return service.analysis_public(session, project, row)


@router.get(
    "/netflow-analyses/{analysis_id}/reconcile/operations/{key}",
    response_model=service.AnalysisPublic,
)
def reconcile_operation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    response: Response,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
    key: str,
) -> service.AnalysisPublic:
    _private(response)
    project = project_for(session, current_user, project_id)
    identifier = operation_result(
        session, project, current_user.id, f"reconcile:{analysis_id}", key
    )
    if identifier is None or identifier != analysis_id:
        deny("netflow_analysis_not_found", 404)
    return service.analysis_public(
        session, project, service.analysis_for(session, project, identifier)
    )
