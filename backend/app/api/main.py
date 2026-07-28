from fastapi import APIRouter

from app.api.routes import audit_events, login, projects, users

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(projects.router)
api_router.include_router(audit_events.router)
