import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Response

from app.api.deps import CurrentUser, SessionDep
from app.domain import comparison_results as service
from app.domain.netflow_common import project_for

router = APIRouter(prefix="/projects/{project_id}/comparison-results", tags=["comparison-results"])
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
Skip = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


@router.post("/scope-confirmations", response_model=service.ResultPublic, status_code=201)
def confirm_scope(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, body: service.ConfirmScope, idempotency_key: Key) -> service.ResultPublic:
    return service.confirm_scope(session, project_for(session, current_user, project_id, write=True, admin=True), current_user, body, idempotency_key)


@router.get("/readiness", response_model=service.Readiness)
def readiness(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, response: Response, scope_confirmation_id: uuid.UUID | None = None) -> service.Readiness:
    _private(response)
    return service.readiness(session, project_for(session, current_user, project_id), scope_confirmation_id)


@router.get("/current", response_model=service.ResultPublic)
def current(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, response: Response, scope_confirmation_id: uuid.UUID | None = None) -> service.ResultPublic:
    _private(response)
    project = project_for(session, current_user, project_id)
    ready = service.readiness(session, project, scope_confirmation_id)
    if ready.state != "READY" or ready.expected_current_result_id is None:
        from app.domain.netflow_common import deny
        deny("comparison_current_not_available", 404)
    return service._public(service._result(session, project, ready.expected_current_result_id))


@router.post("", response_model=service.ResultPublic, status_code=201)
def create(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, body: service.CreateResult, idempotency_key: Key) -> service.ResultPublic:
    return service.create(session, project_for(session, current_user, project_id, write=True), current_user, body, idempotency_key)


@router.get("/operations/{key}", response_model=service.ResultPublic)
def operation(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, key: str, response: Response) -> service.ResultPublic:
    _private(response)
    project = project_for(session, current_user, project_id)
    from app.domain.netflow_common import deny, operation_result
    result = operation_result(session, project, current_user.id, "comparison:create", key)
    if result is None:
        deny("comparison_result_not_found", 404)
    return service._public(service._result(session, project, result))


@router.get("/{result_id}/summary", response_model=service.ResultSummary)
def summary(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, result_id: uuid.UUID, response: Response) -> service.ResultSummary:
    _private(response)
    return service.summary(session, project_for(session, current_user, project_id), result_id)


@router.get("/{result_id}/addresses", response_model=service.AddressPage)
def addresses(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, result_id: uuid.UUID, response: Response, classification: Literal["all", "both", "cloud_only", "customer_only"] = "all", ip: str | None = None, skip: Skip = 0, limit: Limit = 25) -> service.AddressPage:
    _private(response)
    return service.addresses(session, project_for(session, current_user, project_id), result_id, classification, ip, skip, limit)
