from fastapi import APIRouter, Depends
from sqlmodel import SQLModel

from app.api.deps import SessionDep, get_current_active_superuser
from app.core.config import settings
from app.domain import model_connections
from app.domain.model_qualification import (
    current_model_is_qualified,
    model_binding,
)
from app.domain.models import DEPLOYMENT_TENANT_ID, ModelConnectionState

router = APIRouter(
    prefix="/model-qualification",
    tags=["model-qualification"],
    dependencies=[Depends(get_current_active_superuser)],
)


class ModelQualificationStatus(SQLModel):
    qualified: bool


@router.get("/status", response_model=ModelQualificationStatus)
def read_model_qualification_status(session: SessionDep) -> ModelQualificationStatus:
    state = session.get(ModelConnectionState, DEPLOYMENT_TENANT_ID)
    if state is not None and state.adopted:
        try:
            model_connections.binding_for_task(session, "qualification")
            if state.active_id is None:
                return ModelQualificationStatus(qualified=False)
            model_connections.provider_key(
                session, model_connections.get_version(session, state.active_id)
            )
        except model_connections.ModelConnectionError:
            return ModelQualificationStatus(qualified=False)
        return ModelQualificationStatus(qualified=True)
    if not settings.MODEL_API_KEY.get_secret_value():
        return ModelQualificationStatus(qualified=False)
    try:
        binding = model_binding(
            endpoint=settings.MODEL_API_ENDPOINT,
            model_identity=settings.MODEL_IDENTITY,
            protocol=settings.MODEL_API_PROTOCOL,
            config_revision=settings.MODEL_CONFIG_REVISION,
            runner_build_version=settings.RUNNER_BUILD_VERSION,
            agent_compose_runtime_version=settings.AGENT_COMPOSE_RUNTIME_VERSION,
            allow_baizhi_test=settings.MODEL_QUALIFICATION_ALLOW_BAIZHI_TEST,
        )
    except ValueError:
        return ModelQualificationStatus(qualified=False)
    return ModelQualificationStatus(
        qualified=current_model_is_qualified(
            session=session,
            endpoint=binding.endpoint,
            model_identity=binding.model_identity,
            config_fingerprint=binding.config_fingerprint,
        )
    )
