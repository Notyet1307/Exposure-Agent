"""Private responses and non-echoing input errors for the NetFlow API surface."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel


class NetFlowErrorDetail(BaseModel):
    code: str


class NetFlowError(BaseModel):
    detail: NetFlowErrorDetail | str


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": NetFlowError}
    for status in (400, 401, 403, 404, 409, 410, 413, 415, 422, 503)
}


class NetFlowRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                response = await original(request)
            except RequestValidationError:
                response = JSONResponse(
                    status_code=422,
                    content={"detail": {"code": "netflow_artifact_schema_invalid"}},
                )
            except HTTPException as error:
                error.headers = {
                    **(error.headers or {}),
                    "Cache-Control": "private, no-store",
                }
                raise
            response.headers["Cache-Control"] = "private, no-store"
            return response

        return handle
