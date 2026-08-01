from fastapi import APIRouter

from app.api.routes import (
    audit_events,
    cloudatlas_source_instances,
    governance_runs,
    login,
    project_memberships,
    projects,
    users,
)

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(projects.router)
api_router.include_router(cloudatlas_source_instances.router)
api_router.include_router(governance_runs.router)
api_router.include_router(project_memberships.router)
api_router.include_router(audit_events.router)
