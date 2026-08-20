from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from scs_data.identity import ScsIdentityStore
from scs_data.config import ScsPaths
from shared_platform.application import ApplicationContext

from .auth_routes import build_auth_router
from .customer_routes import build_customer_router
from .membership_routes import build_membership_router
from .job_routes import build_job_router
from .import_routes import build_import_router
from .employee_routes import build_employee_router
from .reports_routes import build_reports_router


def _allowed_origins(context: ApplicationContext) -> list[str]:
    origins = {
        f"http://127.0.0.1:{context.web_port}",
        f"http://localhost:{context.web_port}",
        context.public_origin,
    }
    return sorted(origins)


def build_scs_app(context: ApplicationContext, identity: ScsIdentityStore, mailer: object, *, customers=None, memberships=None, jobs=None, reports_paths=None) -> FastAPI:
    ScsPaths.from_context(context)
    app = FastAPI(title="Sunshine Climate Solutions Operations API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(context),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.include_router(build_auth_router(context, identity, mailer))
    app.include_router(build_employee_router(context, identity))
    if customers is not None:
        app.include_router(build_customer_router(context, identity, customers))
    if memberships is not None:
        app.include_router(build_membership_router(context, identity, memberships))
    if jobs is not None:
        app.include_router(build_job_router(context, identity, jobs))
    if customers is not None:
        app.include_router(build_import_router(context, identity, customers))
    if jobs is not None or customers is not None:
        app.include_router(build_reports_router(context, identity, reports_paths))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, error: Exception):
        logging.getLogger("scs_api").exception(
            "unhandled error on %s %s", request.method, request.url.path
        )
        headers = {}
        origin = request.headers.get("origin")
        if origin and origin in _allowed_origins(context):
            headers["Access-Control-Allow-Origin"] = origin
            headers["Vary"] = "Origin"
            headers["Access-Control-Allow-Credentials"] = "true"
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
            headers=headers,
        )

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
