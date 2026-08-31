"""FastAPI application factory and global middleware.

Routers are registered here; all business logic lives in app/services so the
same functions can later be called from a batch job or an Azure Function
without dragging FastAPI along.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db import ping
from app.routers import auth, export, fleet, insights, rules, workflow
from app.logging_config import configure_logging, get_logger, new_request_id, request_id_var

configure_logging()
log = get_logger("fleetguard.api")


class UpstreamLLMError(RuntimeError):
    """Raised when the LLM provider fails. Surfaces as 502 with its message."""


# A stable machine-readable slug per status, so a client can branch on the
# error without string-matching a human sentence that may be reworded.
ERROR_SLUGS = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "invalid_request",
    429: "rate_limited",
}


def create_app() -> FastAPI:
    if not settings.auth_secret_ready:
        # Not fatal while AUTH_ENABLED is false - the demo runs on the scope
        # header - but it must not be discovered the day auth is switched on.
        log.warning(
            "JWT_SECRET is blank or under 32 characters. Login and token "
            "issuing are unsafe until it is set; AUTH_ENABLED=true will "
            "refuse to start."
        )

    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description=(
            "Predictive maintenance for commercial vehicle fleets. "
            "Signals in, ranked risk and remaining useful life out."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or new_request_id()
        token = request_id_var.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = rid
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": elapsed_ms,
            },
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        # Actionable 422: say which field and why, not a raw pydantic dump.
        problems = [
            {
                "field": ".".join(str(p) for p in err["loc"][1:]) or "body",
                "problem": err["msg"],
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "invalid_request",
                "message": "The request could not be processed as sent.",
                "problems": problems,
                "request_id": request_id_var.get(),
            },
        )

    @app.exception_handler(HTTPException)
    async def http_handler(request: Request, exc: HTTPException):
        # Same envelope as every other error, so the frontend needs exactly one
        # parser rather than one for FastAPI's default shape and one for ours.
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": ERROR_SLUGS.get(exc.status_code, "request_failed"),
                "message": exc.detail if isinstance(exc.detail, str) else "Request failed.",
                "request_id": request_id_var.get(),
            },
            headers=exc.headers,
        )

    @app.exception_handler(UpstreamLLMError)
    async def llm_handler(request: Request, exc: UpstreamLLMError):
        log.error("llm_upstream_failure", extra={"detail": str(exc)})
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": "llm_unavailable",
                "message": "The language model provider could not be reached.",
                "provider_message": str(exc),
                "request_id": request_id_var.get(),
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def db_handler(request: Request, exc: SQLAlchemyError):
        log.exception("database_error")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "database_error",
                "message": "A database error occurred.",
                "request_id": request_id_var.get(),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        # Stack traces go to the log, never to the client.
        log.exception("unhandled_error")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_error",
                "message": "Something went wrong on our side.",
                "request_id": request_id_var.get(),
            },
        )

    # Routers hold no business logic: they read parameters, call a service and
    # shape the response. Order is presentational - it is the order the tags
    # appear in /docs, which is part of the demo.
    app.include_router(auth.router)
    app.include_router(insights.router)
    app.include_router(fleet.router)
    app.include_router(rules.router)
    app.include_router(workflow.router)
    app.include_router(export.router)

    @app.get("/api/health", tags=["system"], summary="Liveness probe")
    def health() -> dict:
        return {
            "status": "ok",
            "app": settings.APP_NAME,
            "environment": settings.ENVIRONMENT,
        }

    @app.get("/api/health/ready", tags=["system"], summary="Readiness probe")
    def ready() -> JSONResponse:
        database_ok = ping()
        llm_ok = settings.llm_configured
        payload = {
            "status": "ready" if database_ok else "degraded",
            "database": "ok" if database_ok else "unreachable",
            "llm": "configured" if llm_ok else "not_configured",
        }
        code = status.HTTP_200_OK if database_ok else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(status_code=code, content=payload)

    return app


app = create_app()
