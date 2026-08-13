from __future__ import annotations

from fastapi import FastAPI

from scs_data.identity import ScsIdentityStore
from scs_data.config import ScsPaths
from shared_platform.application import ApplicationContext

from .auth_routes import build_auth_router
from .customer_routes import build_customer_router
from .membership_routes import build_membership_router
from .job_routes import build_job_router
from .import_routes import build_import_router


def build_scs_app(context: ApplicationContext, identity: ScsIdentityStore, mailer: object, *, customers=None, memberships=None, jobs=None) -> FastAPI:
    ScsPaths.from_context(context)
    app = FastAPI(title="Sunshine Climate Solutions Operations API", version="0.1.0")
    app.include_router(build_auth_router(context, identity, mailer))
    if customers is not None:
        app.include_router(build_customer_router(context, identity, customers))
    if memberships is not None:
        app.include_router(build_membership_router(context, identity, memberships))
    if jobs is not None:
        app.include_router(build_job_router(context, identity, jobs))
    if customers is not None:
        app.include_router(build_import_router(context, identity, customers))

    @app.get("/health")
    def health():
        try:
            version = identity.conn.execute("SELECT MAX(version) FROM scs_schema_migrations").fetchone()[0]
            app_id = identity.conn.execute("SELECT application_id FROM scs_application_metadata WHERE singleton=1").fetchone()[0]
            ok = app_id == "scs" and int(version) >= 1
        except Exception:
            ok, version = False, None
        return {"ok": ok, "application_id": "scs", "schema_version": version}

    return app
