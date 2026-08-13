from __future__ import annotations

from fastapi import FastAPI

from scs_data.identity import ScsIdentityStore
from shared_platform.application import ApplicationContext

from .auth_routes import build_auth_router
from .customer_routes import build_customer_router
from .membership_routes import build_membership_router
from .job_routes import build_job_router


def build_scs_app(context: ApplicationContext, identity: ScsIdentityStore, mailer: object, *, customers=None, memberships=None, jobs=None) -> FastAPI:
    if context.application_id != "scs":
        raise ValueError("SCS app requires explicit SCS context")
    app = FastAPI(title="Sunshine Climate Solutions Operations API", version="0.1.0")
    app.include_router(build_auth_router(context, identity, mailer))
    if customers is not None:
        app.include_router(build_customer_router(context, identity, customers))
    if memberships is not None:
        app.include_router(build_membership_router(context, identity, memberships))
    if jobs is not None:
        app.include_router(build_job_router(context, identity, jobs))

    @app.get("/health")
    def health():
        return {"ok": True, "application_id": "scs"}

    return app
