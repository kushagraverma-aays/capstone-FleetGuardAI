"""FastAPI application factory and global middleware.

Routers are registered here; all business logic lives in app/services so the
same functions can later be called from a batch job or an Azure Function
without dragging FastAPI along.

The app also serves the built React bundle when one is present next to it, so a
single-process deployment - a Databricks App, a container behind one hostname -
needs no separate web server and the browser makes no cross-origin call.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.db import ping
from app.rate_limit import limiter, rate_limit_response
from app.routers import auth, chat, export, fleet, insights, rules, workflow
from app.logging_config import configure_logging, get_logger, new_request_id, request_id_var
from app.services.llm import LLMBudgetExceeded, UpstreamLLMError

configure_logging()
log = get_logger("fleetguard.api")


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

    # slowapi reads the limiter off app.state and needs its own handler for the
    # 429, or the generic Exception handler would turn a rate limit into a 500.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_response)

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

    @app.exception_handler(LLMBudgetExceeded)
    async def llm_budget_handler(request: Request, exc: LLMBudgetExceeded):
        # 429, not 502. The provider is up and the request was well formed; the
        # minute's token allowance is simply spent. That is a wait, not a
        # failure, and the assistant panel words the two very differently.
        log.warning("llm_budget_exceeded", extra={"detail": str(exc)})
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error": "llm_busy",
                "message": (
                    "The assistant has used this minute's allowance of language "
                    "model capacity. Wait a few seconds and ask again."
                ),
                "provider_message": str(exc),
                "request_id": request_id_var.get(),
            },
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
    app.include_router(chat.router)

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

    _mount_frontend(app)

    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built React bundle from <deploy root>/static, if it is there.

    Registered last on purpose. The catch-all below matches every path, so any
    route added after it would be shadowed - every /api call would answer with
    index.html instead. Nothing is mounted at all when the directory is absent,
    which is the normal case in development: the Vite dev server owns the UI
    and proxies /api here, and mounting a stale bundle would only confuse that.
    """
    static_dir = Path(__file__).resolve().parent.parent / "static"
    if not (static_dir / "index.html").is_file():
        return

    # Vite emits hashed filenames under assets/, so these can be cached hard by
    # anything in front of the app; index.html must not be.
    if (static_dir / "assets").is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(static_dir / "assets")),
            name="frontend_assets",
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        # An unmatched /api path is a genuine 404 and must answer with the JSON
        # envelope every other error uses. Without this it would fall through to
        # index.html below - a 200 full of HTML, which the client tries to parse
        # as JSON and reports as a parse failure instead of a missing endpoint.
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Unknown endpoint."
            )

        # A real file wins; everything else falls back to index.html so that a
        # deep link like /vehicles/TRK-004 is handled by the client router
        # rather than answering 404 on a hard refresh. The containment check
        # stops "../" in the path from reaching outside the bundle.
        candidate = (static_dir / full_path).resolve()
        if candidate.is_relative_to(static_dir) and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(static_dir / "index.html"))


app = create_app()
