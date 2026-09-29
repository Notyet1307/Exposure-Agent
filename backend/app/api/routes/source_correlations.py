"""Version-pinned source correlation API; all reads reauthorize every input."""
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Response
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.domain import source_correlations as service
from app.domain.netflow_common import deny, operation_result, project_for, request_hash
from app.domain.netflow_models import SourceCorrelationRevision

router = APIRouter(prefix="/projects/{project_id}/source-correlations", tags=["source-correlations"])
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
Skip = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


@router.post("", response_model=service.RevisionPublic, status_code=201)
def create_correlation(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, body: service.Selection, idempotency_key: Key) -> service.RevisionPublic:
    project = project_for(session, current_user, project_id, write=True)
    return service.create(session, project, current_user, body, idempotency_key)


@router.get("", response_model=service.RevisionPage)
def list_correlations(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, response: Response,
    dataset_id: uuid.UUID | None = None, network_namespace: str | None = None, skip: Skip = 0, limit: Limit = 25) -> service.RevisionPage:
    _private(response)
    project = project_for(session, current_user, project_id)
    query = select(SourceCorrelationRevision).where(SourceCorrelationRevision.project_id == project.id, SourceCorrelationRevision.tenant_id == project.tenant_id)
    if network_namespace is not None:
        query = query.where(SourceCorrelationRevision.network_namespace == network_namespace)
    rows = session.exec(query.order_by(col(SourceCorrelationRevision.created_at).desc(), col(SourceCorrelationRevision.id).desc())).all()
    if dataset_id is not None:
        rows = [row for row in rows if row.pins.get("NETFLOW", {}).get("dataset_id") == str(dataset_id)]
    data = []
    for index, row in enumerate(rows):
        loaded = service.materials(session, project, service.Selection.model_validate(row.selection))
        if request_hash({s: m.pins for s, m in loaded.items()}) != request_hash(row.pins):
            deny("netflow_artifact_integrity_failed")
        current = service.current_for(session, row)
        if skip <= index < skip + limit:
            data.append(service.public(row, current))
    return service.RevisionPage(project_id=project.id, data=data, count=len(rows), skip=skip, limit=limit)


@router.get("/operations/{key}", response_model=service.RevisionPublic)
def creation_operation(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, key: str, response: Response) -> service.RevisionPublic:
    _private(response)
    project = project_for(session, current_user, project_id)
    result_id = operation_result(session, project, current_user.id, "correlation:create", key)
    if result_id is None:
        deny("correlation_not_found", 404)
    row = service.revision_for(session, project, result_id)
    loaded = service.materials(session, project, service.Selection.model_validate(row.selection))
    if request_hash({s: m.pins for s, m in loaded.items()}) != request_hash(row.pins):
        deny("netflow_artifact_integrity_failed")
    current = service.current_for(session, row)
    return service.public(row, current)


@router.post("/{revision_id}/scope-revisions", response_model=service.RevisionPublic, status_code=201)
def scope_revision(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, revision_id: uuid.UUID, body: service.ScopeChange, idempotency_key: Key) -> service.RevisionPublic:
    project = project_for(session, current_user, project_id, write=True, admin=True)
    return service.change_scope(session, project, current_user, revision_id, body, idempotency_key)


@router.get("/{revision_id}/scope-revisions/operations/{key}", response_model=service.RevisionPublic)
def scope_operation(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, revision_id: uuid.UUID, key: str, response: Response) -> service.RevisionPublic:
    _private(response)
    project = project_for(session, current_user, project_id)
    parent = service.revision_for(session, project, revision_id)
    result_id = operation_result(session, project, current_user.id, f"correlation:scope:{parent.root_id}", key)
    if result_id is None:
        deny("correlation_not_found", 404)
    row = service.revision_for(session, project, result_id)
    # Recovery remains possible for the actor who just revoked this chain; input access still applies.
    loaded = service.materials(session, project, service.Selection.model_validate(row.selection))
    if request_hash({s: m.pins for s, m in loaded.items()}) != request_hash(row.pins):
        deny("netflow_artifact_integrity_failed")
    return service.public(row, service.current_for(session, row))


@router.get("/{revision_id}", response_model=service.Summary)
def summary(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, revision_id: uuid.UUID, response: Response) -> service.Summary:
    _private(response)
    project = project_for(session, current_user, project_id)
    row = service.revision_for(session, project, revision_id)
    current, loaded = service.read_material(session, project, row)
    addresses = service.addresses(session, project, row, loaded)
    intersections = None
    if row.scope_state == "CONFIRMED":
        intersections = {"+".join(s for index, s in enumerate(service.SOURCES) if mask & (1 << index)): 0 for mask in range(1, 8)}
        for address in addresses:
            intersections["+".join(address.positive_sources)] += 1
    return service.Summary(**service.public(row, current).model_dump(), sources=[m.state for m in loaded.values()], total_addresses=len(addresses),
        positive_intersections=intersections, test_fixture=loaded["NETFLOW"].test_fixture, limitations=[] if row.scope_state == "CONFIRMED" else ["SCOPE_UNCONFIRMED"])


@router.get("/{revision_id}/addresses", response_model=service.AddressPage)
def list_addresses(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, revision_id: uuid.UUID, response: Response,
    ip: str | None = None, positive_sources: str | None = None, unmatched_netflow: bool | None = None, has_review_task: bool | None = None,
    sort: Literal["ip_asc", "ip_desc"] = "ip_asc", skip: Skip = 0, limit: Limit = 25) -> service.AddressPage:
    _private(response)
    project = project_for(session, current_user, project_id)
    row = service.revision_for(session, project, revision_id)
    _, loaded = service.read_material(session, project, row)
    all_rows = service.addresses(session, project, row, loaded)
    canonical_ip = service.canonical(ip) if ip is not None else None
    sources = set(positive_sources.split(",")) if positive_sources is not None else None
    if sources is not None and (not sources or not sources.issubset(service.SOURCES)):
        deny("netflow_context_invalid", 422)
    matches = [a for a in all_rows if (canonical_ip is None or a.canonical_ip == canonical_ip)
        and (sources is None or set(a.positive_sources) == sources)
        and (unmatched_netflow is None or a.unmatched_netflow == unmatched_netflow)
        and (has_review_task is None or bool(a.task_refs) == has_review_task)]
    if sort == "ip_desc":
        matches.reverse()
    return service.AddressPage(project_id=project.id, correlation_revision_id=row.id, network_namespace=row.network_namespace,
        data=matches[skip:skip + limit], count=len(matches), skip=skip, limit=limit, total_addresses=len(all_rows), source_totals={s: m.state.source_addresses for s, m in loaded.items()})


@router.get("/{revision_id}/addresses/{address_key}", response_model=service.AddressPublic)
def address_detail(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, revision_id: uuid.UUID, address_key: str, response: Response) -> service.AddressPublic:
    _private(response)
    project = project_for(session, current_user, project_id)
    row = service.revision_for(session, project, revision_id)
    _, loaded = service.read_material(session, project, row)
    return service.selected_address(session, project, row, loaded, address_key)


@router.get("/{revision_id}/addresses/{address_key}/services", response_model=service.ServicePage)
def address_services(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, revision_id: uuid.UUID, address_key: str, response: Response, skip: Skip = 0, limit: Limit = 25) -> service.ServicePage:
    _private(response)
    project = project_for(session, current_user, project_id)
    row = service.revision_for(session, project, revision_id)
    _, loaded = service.read_material(session, project, row)
    address = service.selected_address(session, project, row, loaded, address_key)
    return service.services(row, address, loaded, skip, limit)


@router.get("/{revision_id}/addresses/{address_key}/evidence", response_model=service.EvidencePage)
def address_evidence(*, session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID, revision_id: uuid.UUID, address_key: str,
    source: Literal["customer", "cloud", "netflow"], response: Response, skip: Skip = 0, limit: Limit = 25) -> service.EvidencePage:
    _private(response)
    project = project_for(session, current_user, project_id)
    row = service.revision_for(session, project, revision_id)
    _, loaded = service.read_material(session, project, row)
    address = service.selected_address(session, project, row, loaded, address_key)
    source_name: service.Source = "CUSTOMER" if source == "customer" else "CLOUD" if source == "cloud" else "NETFLOW"
    return service.evidence(row, address, loaded, source_name, skip, limit)
