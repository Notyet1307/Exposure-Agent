"""Result-first, local-only C/A publications and optional versioned evidence."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.netflow_http import ERROR_RESPONSES, NetFlowRoute
from app.domain import comparison_results as service
from app.domain.netflow_common import project_for

router = APIRouter(
    prefix="/projects/{project_id}/comparison-results",
    tags=["comparison-results"],
    route_class=NetFlowRoute,
    responses=ERROR_RESPONSES,
)
Key = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]
Skip = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]
ScopeKey = Annotated[str | None, Query(pattern=r"^[a-f0-9]{64}$")]
Namespace = Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]


@router.post(
    "/scope-confirmations", response_model=service.ConfirmationPublic, status_code=201
)
def confirm_scope(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    body: service.ConfirmScope,
    idempotency_key: Key,
) -> service.ConfirmationPublic:
    return service.confirm_scope(
        session,
        project_for(session, current_user, project_id, write=True, admin=True),
        current_user,
        body,
        idempotency_key,
    )


@router.get("/readiness", response_model=service.Readiness)
def readiness(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    source_instance_id: uuid.UUID | None = None,
    network_namespace: Namespace = None,
    result_id: uuid.UUID | None = None,
) -> service.Readiness:
    project = project_for(session, current_user, project_id)
    base = service._result(session, project, result_id) if result_id else None
    if base:
        service._read(session, project, base)
    return service.readiness(
        session,
        project,
        current_user,
        source_instance_id=source_instance_id,
        network_namespace=network_namespace,
        base=base,
    )


@router.get("/current", response_model=service.CurrentResult)
def current(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    scope_key: ScopeKey = None,
) -> service.CurrentResult:
    return service.current(
        session, project_for(session, current_user, project_id), current_user, scope_key
    )


@router.get("/history", response_model=service.ResultHistory)
def history(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    scope_key: ScopeKey = None,
    skip: Skip = 0,
    limit: Limit = 25,
) -> service.ResultHistory:
    return service.history(
        session, project_for(session, current_user, project_id), scope_key, skip, limit
    )


@router.post("", response_model=service.ResultPublic, status_code=201)
def create(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    body: service.CreateResult,
    idempotency_key: Key,
) -> service.ResultPublic:
    return service.create(
        session,
        project_for(session, current_user, project_id, write=True),
        current_user,
        body,
        idempotency_key,
    )


@router.get("/operations/{key}", response_model=service.OperationPublic)
def operation(
    *, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, key: str
) -> service.OperationPublic:
    return service.operation(
        session, project_for(session, current_user, project_id), current_user, key
    )


@router.get("/{result_id}/summary", response_model=service.ResultSummary)
def summary(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    result_id: uuid.UUID,
) -> service.ResultSummary:
    return service.summary(
        session, project_for(session, current_user, project_id), result_id
    )


@router.get("/{result_id}/updates", response_model=service.Updates)
def updates(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    result_id: uuid.UUID,
) -> service.Updates:
    return service.updates(
        session, project_for(session, current_user, project_id), current_user, result_id
    )


@router.get("/{result_id}/addresses", response_model=service.AddressPage)
def addresses(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    classification: service.Classification = "all",
    ip: Annotated[str | None, Query(max_length=45)] = None,
    skip: Skip = 0,
    limit: Limit = 25,
    sort: Literal["ip_asc", "ip_desc"] = "ip_asc",
) -> service.AddressPage:
    return service.addresses(
        session,
        project_for(session, current_user, project_id),
        result_id,
        classification,
        ip,
        skip,
        limit,
        sort,
    )


@router.get(
    "/{result_id}/addresses/{address_key}/evidence", response_model=service.EvidencePage
)
def evidence(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    address_key: str,
    source: Literal["customer", "cloud"],
    skip: Skip = 0,
    limit: Limit = 25,
) -> service.EvidencePage:
    return service.evidence(
        session,
        project_for(session, current_user, project_id),
        result_id,
        address_key,
        source,
        skip,
        limit,
    )


@router.get("/{result_id}/supplements", response_model=service.SupplementPublic)
def current_supplement(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    result_id: uuid.UUID,
) -> service.SupplementPublic:
    return service.supplement(
        session, project_for(session, current_user, project_id), result_id
    )


@router.post(
    "/{result_id}/supplements", response_model=service.SupplementPublic, status_code=201
)
def bind_supplement(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    body: service.SupplementCreate,
    idempotency_key: Key,
) -> service.SupplementPublic:
    return service.bind(
        session,
        project_for(session, current_user, project_id, write=True),
        current_user,
        result_id,
        body,
        idempotency_key,
    )


@router.get(
    "/{result_id}/supplements/operations/{key}", response_model=service.SupplementPublic
)
def supplement_operation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    key: str,
) -> service.SupplementPublic:
    return service.supplement_operation(
        session,
        project_for(session, current_user, project_id),
        current_user,
        result_id,
        key,
    )


@router.get(
    "/{result_id}/supplements/history", response_model=service.SupplementHistory
)
def supplement_history(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    skip: Skip = 0,
    limit: Limit = 25,
) -> service.SupplementHistory:
    return service.supplement_history(
        session, project_for(session, current_user, project_id), result_id, skip, limit
    )


@router.get(
    "/{result_id}/supplements/{binding_id}", response_model=service.SupplementPublic
)
def fixed_supplement(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    binding_id: uuid.UUID,
) -> service.SupplementPublic:
    return service.supplement(
        session, project_for(session, current_user, project_id), result_id, binding_id
    )


@router.get(
    "/{result_id}/supplements/{binding_id}/addresses",
    response_model=service.SupplementAddresses,
)
def supplement_addresses(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    binding_id: uuid.UUID,
    only_supplemental: bool = False,
    ip: Annotated[list[str] | None, Query(max_length=100)] = None,
    skip: Skip = 0,
    limit: Limit = 25,
) -> service.SupplementAddresses:
    return service.supplement_addresses(
        session,
        project_for(session, current_user, project_id),
        result_id,
        binding_id,
        only_supplemental=only_supplemental,
        ips=ip,
        skip=skip,
        limit=limit,
    )
