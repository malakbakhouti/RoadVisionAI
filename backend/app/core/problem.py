"""RFC 7807 `application/problem+json` error responses (APISpec v1.0 error model)."""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_TITLES = {
    status.HTTP_400_BAD_REQUEST: "Bad Request",
    status.HTTP_401_UNAUTHORIZED: "Unauthorized",
    status.HTTP_403_FORBIDDEN: "Forbidden",
    status.HTTP_404_NOT_FOUND: "Not Found",
    status.HTTP_409_CONFLICT: "Conflict",
    422: "Validation Error",
}


def problem(status_code: int, detail: str, instance: str | None = None) -> JSONResponse:
    body = {
        "type": "about:blank",
        "title": _TITLES.get(status_code, "Error"),
        "status": status_code,
        "detail": detail,
    }
    if instance:
        body["instance"] = instance
    return JSONResponse(
        status_code=status_code, content=body, media_type="application/problem+json"
    )


def register_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exc_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        resp = problem(exc.status_code, str(exc.detail), str(request.url.path))
        if exc.headers:
            resp.headers.update(exc.headers)
        return resp

    @app.exception_handler(RequestValidationError)
    async def validation_exc_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        resp = problem(422, "Request validation failed", str(request.url.path))
        return resp
