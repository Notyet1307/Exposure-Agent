"""One read-only GET over existing readiness, source and optional NetFlow state."""

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.netflow_http import ERROR_RESPONSES, NetFlowRoute
from app.domain import input_summary as service
from app.domain.netflow_common import project_for

router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["input-summary"],
    route_class=NetFlowRoute,
    responses=ERROR_RESPONSES,
)


@router.get(
    "/input-summary",
    response_model=service.InputSummary,
    operation_id="read_input_summary",
)
def read_input_summary(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
) -> service.InputSummary:
    return service.compose(
        session, project_for(session, current_user, project_id), current_user
    )
