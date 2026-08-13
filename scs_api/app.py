from __future__ import annotations

from fastapi import FastAPI

from scs_data.identity import ScsIdentityStore
from shared_platform.application import ApplicationContext

from .auth_routes import build_auth_router


def build_scs_app(context: ApplicationContext, identity: ScsIdentityStore, mailer: object) -> FastAPI:
    if context.application_id != "scs":
        raise ValueError("SCS app requires explicit SCS context")
    app = FastAPI(title="Sunshine Climate Solutions Operations API", version="0.1.0")
    app.include_router(build_auth_router(context, identity, mailer))

    @app.get("/health")
    def health():
        return {"ok": True, "application_id": "scs"}

    return app
