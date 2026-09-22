"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cie.api.routes_core import router as core_router
from cie.core.logging import configure_logging
from cie.core.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="Company Intelligence Engine", version="0.1.0",
                  description="Organizational memory and multi-agent operating system. All answers cite evidence.")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(core_router, prefix="/api")
    try:
        from cie.api.routes_agents import router as agents_router

        app.include_router(agents_router, prefix="/api")
    except ImportError:  # agents routes are added in phase 3
        pass
    try:
        from cie.api.routes_governance import router as gov_router

        app.include_router(gov_router, prefix="/api")
    except ImportError:
        pass
    return app


app = create_app()
