"""FastAPI application: every route under /api. `uvicorn clipsieve.app:app`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from clipsieve.api import events, meta, runs
from clipsieve.api.context import AppContext, get_context, set_context
from clipsieve.logging import configure_logging


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
        parts.append(f"{loc}: {err.get('msg', 'invalid')}" if loc else str(err.get("msg")))
    return "; ".join(parts) or "invalid request"


async def _on_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Errors are `{"detail": str}` everywhere, request validation included."""
    return JSONResponse(status_code=422, content={"detail": _validation_message(exc)})


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()  # under a server only; in-process test transports skip lifespan
    yield


def create_app(ctx: AppContext | None = None) -> FastAPI:
    if ctx is not None:
        set_context(ctx)
    app = FastAPI(title="clipsieve", lifespan=_lifespan)
    app.add_exception_handler(RequestValidationError, _on_validation_error)
    app.include_router(runs.router, prefix="/api")
    app.include_router(events.router, prefix="/api")
    app.include_router(meta.router, prefix="/api")

    @app.get("/api/health", response_model_exclude_none=True)
    async def health() -> dict[str, str]:
        return {"status": "ok", "backend": get_context().settings.clipsieve_explain_backend}

    return app


# The context is built lazily on the first request, so importing this module is cheap.
app = create_app()
