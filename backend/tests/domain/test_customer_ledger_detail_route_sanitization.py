import uuid

from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from app.api.routes.customer_ledger import _PrivateNoStoreRoute
from app.domain import customer_ledger as service
from app.main import sanitized_validation_exception_handler

SENTINEL = "sentinel-rejected-detail-value"
NEUTRAL_MESSAGE = "Input tag does not match any of the expected tags."


def _details_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(
        RequestValidationError, sanitized_validation_exception_handler
    )
    router = APIRouter(route_class=_PrivateNoStoreRoute)

    @router.post("/details")
    def details(_body: service.ReplacementDetailsRequest) -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    return app


def _basis() -> dict[str, str]:
    return {
        "candidate_upload_id": str(uuid.uuid4()),
        "expected_upload_id": str(uuid.uuid4()),
        "expected_revision_id": str(uuid.uuid4()),
        "expected_profile_id": str(uuid.uuid4()),
    }


def test_detail_route_sanitizes_union_tag_validation_error() -> None:
    client = TestClient(_details_app())
    response = client.post(
        "/details",
        json={
            "basis": _basis(),
            "selector": {"kind": SENTINEL, "category": "added"},
        },
    )

    assert response.status_code == 422, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    errors = response.json()["detail"]
    assert isinstance(errors, list)
    assert len(errors) == 1
    error = errors[0]
    assert error["type"] == "union_tag_invalid"
    assert error["loc"] == ["body", "selector"]
    assert "input" not in error
    assert SENTINEL not in response.text
    assert "tag" not in error.get("ctx", {})
    assert error["ctx"]["discriminator"] == "'kind'"
    assert error["ctx"]["expected_tags"] == "'groups', 'records'"
    assert error["msg"] == NEUTRAL_MESSAGE


def test_detail_route_keeps_generic_validation_errors_sanitized() -> None:
    client = TestClient(_details_app())
    response = client.post(
        "/details",
        json={
            "basis": _basis(),
            "selector": {"kind": "groups", "category": SENTINEL},
        },
    )

    assert response.status_code == 422, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    errors = response.json()["detail"]
    assert isinstance(errors, list)
    assert errors
    assert all("input" not in error for error in errors)
    assert SENTINEL not in response.text
