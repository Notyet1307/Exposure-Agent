import logging
import uuid
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.project_authorization import (
    PROJECT_READ_ROLES,
    get_authorized_project,
    project_access_filter,
)
from app.api.request import get_request_ip_address
from app.core.config import settings
from app.domain import customer_uploads as customer_upload_service
from app.domain import projects as project_service
from app.domain.models import (
    CustomerUpload,
    CustomerUploadProfile,
    CustomerUploadProfileDefinition,
    CustomerUploadProfilePublic,
    CustomerUploadPublic,
    CustomerUploadsPublic,
    Project,
    ProjectCreate,
    ProjectPublic,
    ProjectRole,
    ProjectsPublic,
    ProjectUpdate,
)

_UPLOAD_ERRORS = {
    "invalid_filename": (
        status.HTTP_400_BAD_REQUEST,
        "The upload filename is invalid.",
    ),
    "incomplete_upload": (
        status.HTTP_400_BAD_REQUEST,
        "The upload was incomplete.",
    ),
    "upload_too_large": (
        status.HTTP_413_CONTENT_TOO_LARGE,
        "The upload exceeds the allowed size.",
    ),
    "workbook_resource_limit": (
        status.HTTP_413_CONTENT_TOO_LARGE,
        "The workbook exceeds safe resource limits.",
    ),
    "unsupported_workbook_type": (
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        "Only XLSX workbooks are supported.",
    ),
    "malformed_workbook": (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "The workbook is malformed.",
    ),
    "unsupported_workbook_feature": (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "The workbook contains an unsupported feature.",
    ),
    "missing_required_structure": (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "The workbook is missing required structure.",
    ),
    "invalid_required_value": (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "The workbook contains an invalid required value.",
    ),
    "upload_storage_failed": (
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "The upload could not be stored.",
    ),
}

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "/",
    response_model=ProjectPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_active_superuser)],
)
def create_project(
    *,
    session: SessionDep,
    project_in: ProjectCreate,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    return project_service.create_project(
        session=session,
        project_in=project_in,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )


@router.get("/", response_model=ProjectsPublic)
def read_projects(
    session: SessionDep,
    current_user: CurrentUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> Any:
    access_filter = project_access_filter(
        user=current_user, allowed_roles=PROJECT_READ_ROLES
    )
    count_statement = select(func.count()).select_from(Project).where(access_filter)
    statement = select(Project).where(access_filter)
    count = session.exec(count_statement).one()
    statement = (
        statement.order_by(col(Project.created_at).desc(), col(Project.id).desc())
        .offset(skip)
        .limit(limit)
    )
    projects = session.exec(statement).all()
    return ProjectsPublic(
        data=[ProjectPublic.model_validate(project) for project in projects],
        count=count,
    )


@router.get("/{project_id}", response_model=ProjectPublic)
def read_project(
    *, session: SessionDep, project_id: uuid.UUID, current_user: CurrentUser
) -> Any:
    return get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )


@router.get(
    "/{project_id}/customer-upload-profile",
    response_model=CustomerUploadProfilePublic,
)
def read_current_customer_upload_profile(
    *, session: SessionDep, project_id: uuid.UUID, current_user: CurrentUser
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    profile = session.exec(
        select(CustomerUploadProfile).where(
            CustomerUploadProfile.id
            == project.current_customer_upload_profile_id,
            CustomerUploadProfile.project_id == project.id,
        )
    ).one()
    definition = CustomerUploadProfileDefinition.model_validate(profile.definition)
    return CustomerUploadProfilePublic(
        id=profile.id,
        version=profile.version,
        **definition.model_dump(),
    )


@router.post(
    "/{project_id}/customer-uploads",
    response_model=CustomerUploadPublic,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {
                            "file": {
                                "type": "string",
                                "format": "binary",
                                "contentMediaType": "application/octet-stream",
                            }
                        },
                    }
                }
            },
        }
    },
)
async def create_customer_upload(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
    response: Response,
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=(ProjectRole.OPERATOR,),
        writable=True,
    )
    try:
        streamed_upload = await customer_upload_service.stream_customer_upload_request(
            request=request,
            artifact_root=settings.ARTIFACT_ROOT,
        )
        upload, created = customer_upload_service.accept_customer_upload(
            session=session,
            project=project,
            streamed_upload=streamed_upload,
            artifact_root=settings.ARTIFACT_ROOT,
            actor_subject=str(current_user.id),
            ip_address=get_request_ip_address(request),
        )
    except customer_upload_service.CustomerUploadAcceptanceError as error:
        logger.info(
            "Customer upload rejected",
            extra={"project_id": str(project.id), "upload_error_code": error.code},
        )
        error_status, error_message = _UPLOAD_ERRORS[error.code]
        detail: dict[str, Any] = {
            "code": error.code,
            "message": error_message,
        }
        if error.field is not None:
            detail["field"] = error.field
        if error.row is not None:
            detail["row"] = error.row
        raise HTTPException(status_code=error_status, detail=detail)
    response.status_code = (
        status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )
    return CustomerUploadPublic.model_validate(upload)


@router.get(
    "/{project_id}/customer-uploads",
    response_model=CustomerUploadsPublic,
)
def read_customer_uploads(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    current_user: CurrentUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    count = session.exec(
        select(func.count())
        .select_from(CustomerUpload)
        .where(CustomerUpload.project_id == project.id)
    ).one()
    uploads = session.exec(
        select(CustomerUpload)
        .where(CustomerUpload.project_id == project.id)
        .order_by(
            col(CustomerUpload.created_at).desc(), col(CustomerUpload.id).desc()
        )
        .offset(skip)
        .limit(limit)
    ).all()
    has_operator_access = session.exec(
        select(func.count())
        .select_from(Project)
        .where(
            Project.id == project.id,
            project_access_filter(
                user=current_user, allowed_roles=(ProjectRole.OPERATOR,)
            ),
        )
    ).one()
    can_change_inputs = project.archived_at is None and has_operator_access > 0
    return CustomerUploadsPublic(
        data=[CustomerUploadPublic.model_validate(upload) for upload in uploads],
        count=count,
        current_customer_upload_id=project.current_customer_upload_id,
        can_upload=can_change_inputs,
        can_select=can_change_inputs,
    )


@router.post(
    "/{project_id}/customer-uploads/{upload_id}/select",
    response_model=CustomerUploadPublic,
)
def select_current_customer_upload(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    upload_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=(ProjectRole.OPERATOR,),
        writable=True,
    )
    upload = session.exec(
        select(CustomerUpload).where(
            CustomerUpload.id == upload_id,
            CustomerUpload.project_id == project.id,
        )
    ).one_or_none()
    if upload is None:
        raise HTTPException(status_code=404, detail="CustomerUpload not found")
    return customer_upload_service.select_current_customer_upload(
        session=session,
        project=project,
        upload=upload,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )


@router.post(
    "/{project_id}/archive",
    response_model=ProjectPublic,
)
def archive_project(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None,
        lock=True,
    )

    return project_service.archive_project(
        session=session,
        project=project,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )


@router.post(
    "/{project_id}/reactivate",
    response_model=ProjectPublic,
)
def reactivate_project(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None,
        lock=True,
    )

    return project_service.reactivate_project(
        session=session,
        project=project,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )


@router.patch(
    "/{project_id}",
    response_model=ProjectPublic,
)
def rename_project(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    project_in: ProjectUpdate,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None,
        writable=True,
    )

    return project_service.rename_project(
        session=session,
        project=project,
        project_in=project_in,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )
