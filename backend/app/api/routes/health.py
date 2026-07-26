from fastapi import APIRouter
from sqlmodel import select

from app.api.deps import SessionDep

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def health_live() -> bool:
    return True


@router.get("/ready")
def health_ready(session: SessionDep) -> bool:
    session.exec(select(1)).one()
    return True
