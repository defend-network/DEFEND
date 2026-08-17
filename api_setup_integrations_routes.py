"""Admin-only HTTP surface for the Setup / Integrations control plane.

All routes require an authenticated admin principal. Responses are built from
the integration service's sanitized views; raw secret values never cross this
boundary, and mutation/test endpoints run the synchronous service in a
threadpool so slow provider probes never block the event loop.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from admin_auth import AdminPrincipal, require_admin


class SecretUpdateIn(BaseModel):
    secret_name: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=4096)


class ConfigUpdateIn(BaseModel):
    enabled: bool | None = None
    config: dict[str, str] | None = None


def build_setup_integrations_router(service: Any) -> APIRouter:
    router = APIRouter(prefix="/api/admin/setup", tags=["admin-setup"])

    def _require_service() -> None:
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Setup integration store is unavailable on this host",
            )

    @router.get("/summary")
    async def setup_summary(
        _principal: AdminPrincipal = Depends(require_admin),
    ) -> dict[str, Any]:
        _require_service()
        return await run_in_threadpool(service.snapshot)

    @router.get("/products")
    async def setup_products(
        _principal: AdminPrincipal = Depends(require_admin),
    ) -> dict[str, Any]:
        _require_service()
        return await run_in_threadpool(service.products)

    @router.get("/providers/{provider_id}")
    async def provider_detail(
        provider_id: str,
        _principal: AdminPrincipal = Depends(require_admin),
    ) -> dict[str, Any]:
        _require_service()
        try:
            return await run_in_threadpool(service.provider_view, provider_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Provider not found")

    @router.put("/providers/{provider_id}/secret")
    async def save_secret(
        provider_id: str,
        body: SecretUpdateIn,
        _principal: AdminPrincipal = Depends(require_admin),
    ) -> dict[str, Any]:
        _require_service()
        try:
            return await run_in_threadpool(
                service.save_secret,
                provider_id,
                body.secret_name,
                body.value,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Provider not found")
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @router.delete("/providers/{provider_id}/secret")
    async def remove_secret(
        provider_id: str,
        secret_name: str,
        _principal: AdminPrincipal = Depends(require_admin),
    ) -> dict[str, Any]:
        _require_service()
        try:
            return await run_in_threadpool(
                service.remove_secret, provider_id, secret_name
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Provider not found")
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @router.put("/providers/{provider_id}/config")
    async def update_config(
        provider_id: str,
        body: ConfigUpdateIn,
        _principal: AdminPrincipal = Depends(require_admin),
    ) -> dict[str, Any]:
        _require_service()
        if body.enabled is None and body.config is None:
            raise HTTPException(status_code=400, detail="Nothing to update")
        try:
            return await run_in_threadpool(
                service.save_config,
                provider_id,
                enabled=body.enabled,
                config=body.config,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Provider not found")
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @router.post("/providers/{provider_id}/test")
    async def test_provider(
        provider_id: str,
        _principal: AdminPrincipal = Depends(require_admin),
    ) -> dict[str, Any]:
        _require_service()
        try:
            return await run_in_threadpool(service.test, provider_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Provider not found")
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @router.post("/test-all")
    async def test_all(
        _principal: AdminPrincipal = Depends(require_admin),
    ) -> dict[str, Any]:
        _require_service()
        return await run_in_threadpool(service.test_all_configured)

    @router.get("/diagnostics")
    async def diagnostics(
        _principal: AdminPrincipal = Depends(require_admin),
    ) -> dict[str, Any]:
        _require_service()
        return await run_in_threadpool(service.diagnostics)

    return router