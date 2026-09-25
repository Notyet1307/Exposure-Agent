import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.api.project_authorization import PROJECT_READ_ROLES, get_authorized_project
from app.core.time import get_datetime_utc
from app.domain import external_asset_models as m
from app.domain import external_assets as service
from app.domain.models import Project, ProjectRole, SourceInstance

router = APIRouter(
    prefix="/projects/{project_id}/external-assets", tags=["external-assets"]
)
Skip = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]


def _project(
    session: SessionDep,
    user: CurrentUser,
    project_id: uuid.UUID,
    *,
    write: bool = False,
) -> Project:
    return get_authorized_project(
        session=session,
        user=user,
        project_id=project_id,
        allowed_roles=(ProjectRole.OPERATOR,) if write else PROJECT_READ_ROLES,
        writable=write,
    )


def _sync(
    session: SessionDep, source_id: uuid.UUID, sync_id: uuid.UUID, *, lock: bool = False
) -> m.ExternalSync:
    query = select(m.ExternalSync).where(
        m.ExternalSync.id == sync_id, m.ExternalSync.source_id == source_id
    )
    if lock:
        query = query.with_for_update()
    record = session.exec(query).one_or_none()
    if record is None:
        service.deny("external_sync_not_found", 404)
    assert record is not None
    return record


@router.get("/sources", response_model=m.ExternalSourcesPublic)
def read_external_sources(
    *, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID
) -> m.ExternalSourcesPublic:
    project = _project(session, current_user, project_id)
    sources = session.exec(
        select(SourceInstance)
        .where(
            SourceInstance.project_id == project.id,
            SourceInstance.capability_profile == "assets-v1",
        )
        .order_by(col(SourceInstance.created_at).desc(), col(SourceInstance.id))
    ).all()
    return m.ExternalSourcesPublic(
        data=[service.source_public(s) for s in sources],
        count=len(sources),
        can_manage=service.can_manage(session, current_user, project),
    )


@router.post("/sources", response_model=m.ExternalSourcePublic, status_code=201)
def create_external_source(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    request: m.ExternalSourceCreate,
) -> m.ExternalSourcePublic:
    project = _project(session, current_user, project_id, write=True)
    source = SourceInstance(
        project_id=project.id,
        tenant_id=project.tenant_id,
        capability_profile="assets-v1",
        **request.model_dump(),
    )
    session.add(source)
    service.audit(
        session, source, current_user.id, "external_source.created", source.id
    )
    session.commit()
    session.refresh(source)
    return service.source_public(source)


@router.post("/sources/{source_id}/validate", response_model=m.ExternalSourcePublic)
def validate_external_source(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
) -> m.ExternalSourcePublic:
    project = _project(session, current_user, project_id, write=True)
    source = service.source_for(session, project, source_id, data=False, lock=True)
    try:
        source.validated_fingerprint, source.assets_token_sha256 = service.credentials(
            source
        )
        source.validated_at = get_datetime_utc()
        source.validation_error_code = None
    except service.SyncError as error:
        source.validated_fingerprint = source.assets_token_sha256 = None
        source.validation_error_code = error.code
    source.updated_at = get_datetime_utc()
    session.add(source)
    service.audit(
        session,
        source,
        current_user.id,
        "external_source.validated",
        source.id,
        {"error_code": source.validation_error_code},
    )
    session.commit()
    session.refresh(source)
    return service.source_public(source)


@router.patch("/sources/{source_id}", response_model=m.ExternalSourcePublic)
def update_external_source(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    request: m.ExternalSourceUpdate,
) -> m.ExternalSourcePublic:
    project = _project(session, current_user, project_id, write=True)
    source = service.source_for(session, project, source_id, data=False, lock=True)
    if request.enabled is True:
        try:
            fingerprint, token_hash = service.credentials(source)
        except service.SyncError as error:
            service.deny(error.code)
        if (
            fingerprint != source.validated_fingerprint
            or token_hash != source.assets_token_sha256
            or source.validation_error_code
        ):
            service.deny("external_validation_required")
    for name, value in request.model_dump(exclude_unset=True).items():
        if value is None:
            service.deny("external_source_update_invalid", 422)
        setattr(source, name, value)
    source.updated_at = get_datetime_utc()
    session.add(source)
    service.audit(
        session,
        source,
        current_user.id,
        "external_source.updated",
        source.id,
        {"enabled": source.enabled, "data_access_enabled": source.data_access_enabled},
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        service.deny("cloudatlas_source_conflict")
    session.refresh(source)
    return service.source_public(source)


@router.post(
    "/sources/{source_id}/syncs", response_model=m.ExternalSyncPublic, status_code=202
)
def create_external_sync(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    request: m.ExternalSyncCreate,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
    ],
) -> m.ExternalSyncPublic:
    project = _project(session, current_user, project_id, write=True)
    source = service.source_for(session, project, source_id, lock=True)
    try:
        sync, created = service.reserve_sync(
            session, source, current_user, request, idempotency_key
        )
    except service.SyncError as error:
        service.deny(error.code)
    if created:
        sync = service.launch_sync(session, sync)
    return service.sync_public(session, sync)


@router.get("/sources/{source_id}/syncs", response_model=m.ExternalSyncsPublic)
def read_external_syncs(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    skip: Skip = 0,
    limit: Limit = 25,
) -> m.ExternalSyncsPublic:
    project = _project(session, current_user, project_id)
    source = service.source_for(session, project, source_id)
    query = select(m.ExternalSync).where(m.ExternalSync.source_id == source.id)
    count = session.exec(select(func.count()).select_from(query.subquery())).one()
    rows = session.exec(
        query.order_by(col(m.ExternalSync.created_at).desc(), col(m.ExternalSync.id))
        .offset(skip)
        .limit(limit)
    ).all()
    return m.ExternalSyncsPublic(
        data=[service.sync_public(session, row) for row in rows], count=count
    )


@router.get("/sources/{source_id}/syncs/{sync_id}", response_model=m.ExternalSyncPublic)
def read_external_sync(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    sync_id: uuid.UUID,
) -> m.ExternalSyncPublic:
    project = _project(session, current_user, project_id)
    source = service.source_for(session, project, source_id)
    return service.sync_public(session, _sync(session, source.id, sync_id))


@router.post(
    "/sources/{source_id}/syncs/{sync_id}/reconcile",
    response_model=m.ExternalSyncPublic,
)
def reconcile_external_sync(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    sync_id: uuid.UUID,
) -> m.ExternalSyncPublic:
    project = _project(session, current_user, project_id, write=True)
    source = service.source_for(session, project, source_id, lock=True)
    sync = service.reconcile(session, _sync(session, source.id, sync_id, lock=True))
    service.audit(
        session,
        source,
        current_user.id,
        "external_sync.reconciled",
        sync.id,
        {"status": sync.status},
    )
    session.commit()
    return service.sync_public(session, sync)


@router.get("/sources/{source_id}/versions", response_model=m.ExternalVersionsPublic)
def read_external_versions(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    domain: m.Domain,
    skip: Skip = 0,
    limit: Limit = 25,
) -> m.ExternalVersionsPublic:
    project = _project(session, current_user, project_id)
    source = service.source_for(session, project, source_id)
    query = select(m.ExternalAssetVersion).where(
        m.ExternalAssetVersion.source_id == source.id,
        m.ExternalAssetVersion.domain == domain,
        m.ExternalAssetVersion.space_id == source.space_id,
        m.ExternalAssetVersion.status == "PUBLISHED",
    )
    count = session.exec(select(func.count()).select_from(query.subquery())).one()
    query = query.order_by(
        col(m.ExternalAssetVersion.published_at).desc(), col(m.ExternalAssetVersion.id)
    )
    rows = session.exec(query.offset(skip).limit(limit)).all()
    latest_complete = session.exec(
        query.where(
            col(m.ExternalAssetVersion.complete).is_(True),
            m.ExternalAssetVersion.retain_until > get_datetime_utc(),
        ).limit(1)
    ).first()
    return m.ExternalVersionsPublic(
        data=[service.version_public(row) for row in rows],
        count=count,
        latest_complete_version=(
            service.version_public(latest_complete)
            if latest_complete is not None
            else None
        ),
    )


@router.get("/sources/{source_id}/records", response_model=m.ExternalRecordsPublic)
def read_external_records(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    domain: m.Domain,
    version_id: uuid.UUID | None = None,
    ip: Annotated[str | None, Query(max_length=45)] = None,
    status: Annotated[str | None, Query(max_length=100)] = None,
    skip: Skip = 0,
    limit: Limit = 25,
) -> m.ExternalRecordsPublic:
    project = _project(session, current_user, project_id)
    source = service.source_for(session, project, source_id)
    return service.records(
        session,
        source,
        domain=domain,
        version_id=version_id,
        ip=ip,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/sources/{source_id}/versions/{version_id}/records/{record_id}",
    response_model=m.ExternalRecordDetailPublic,
)
def read_external_record(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    version_id: uuid.UUID,
    record_id: uuid.UUID,
    port_version_id: uuid.UUID | None = None,
    skip: Skip = 0,
    limit: Limit = 25,
) -> m.ExternalRecordDetailPublic:
    project = _project(session, current_user, project_id)
    source = service.source_for(session, project, source_id)
    return service.detail(
        session, source, version_id, record_id, port_version_id, skip, limit
    )


@router.post("/sources/{source_id}/purge-expired", response_model=m.ExternalPurgePublic)
def purge_external_expired(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
) -> m.ExternalPurgePublic:
    project = _project(session, current_user, project_id, write=True)
    source = service.source_for(session, project, source_id, lock=True)
    return m.ExternalPurgePublic(
        deleted_records=service.purge_expired(session, source, current_user)
    )
