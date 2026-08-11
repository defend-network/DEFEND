from __future__ import annotations

import asyncio
import threading
import time

import httpx2
from fastapi import FastAPI

import admin_auth
import api_admin_tt_routes
from api_admin_tt_routes import router as admin_router


def _app(identity, monkeypatch, *, hash_concurrency: int = 1) -> FastAPI:
    monkeypatch.setenv("DEFEND_OWNER_USER", "MASSA")
    monkeypatch.setenv("DEFEND_OWNER_PASS", "valid owner password")
    monkeypatch.setenv("DEFEND_OWNER_EMAIL", "chairman@defend-network.org")
    monkeypatch.setenv(
        "DEFEND_ADMIN_LOGIN_HASH_CONCURRENCY", str(hash_concurrency)
    )
    admin_auth.configure_identity_store(identity)
    app = FastAPI()
    app.include_router(admin_router)

    @app.get("/health-probe")
    async def health_probe():
        await asyncio.sleep(0.01)
        return {"ok": True, "at": time.monotonic()}

    return app


def test_real_admin_password_check_does_not_block_asgi_event_loop(
    identity,
    monkeypatch,
):
    app = _app(identity, monkeypatch)
    real_authenticate = api_admin_tt_routes.authenticate
    password_check_finished_at: list[float] = []

    def observed_real_authenticate(username: str, password: str):
        try:
            return real_authenticate(username, password)
        finally:
            password_check_finished_at.append(time.monotonic())

    monkeypatch.setattr(
        api_admin_tt_routes, "authenticate", observed_real_authenticate
    )

    async def exercise() -> None:
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            login_task = asyncio.create_task(
                client.post(
                    "/api/admin/login",
                    json={
                        "username": "MASSA",
                        "password": "valid owner password",
                    },
                )
            )
            await asyncio.sleep(0)
            health = await client.get("/health-probe")
            login = await login_task

        assert login.status_code == 200
        assert health.status_code == 200
        assert password_check_finished_at
        assert health.json()["at"] < password_check_finished_at[0]

    asyncio.run(exercise())


def test_admin_password_hash_concurrency_saturation_is_bounded_and_generic(
    identity,
    monkeypatch,
):
    app = _app(identity, monkeypatch, hash_concurrency=1)
    real_authenticate = api_admin_tt_routes.authenticate
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def held_real_authenticate(username: str, password: str):
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            entered.set()
            release.wait(timeout=2)
        return real_authenticate(username, password)

    monkeypatch.setattr(api_admin_tt_routes, "authenticate", held_real_authenticate)

    async def exercise() -> None:
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            first_task = asyncio.create_task(
                client.post(
                    "/api/admin/login",
                    json={
                        "username": "MASSA",
                        "password": "valid owner password",
                    },
                )
            )
            deadline = time.monotonic() + 3
            while not entered.is_set() and time.monotonic() < deadline:
                await asyncio.sleep(0.005)
            assert entered.is_set()

            second = await client.post(
                "/api/admin/login",
                json={
                    "username": "MASSA",
                    "password": "valid owner password",
                },
            )
            release.set()
            first = await first_task

        assert first.status_code == 200
        assert second.status_code == 429
        assert second.json() == {"detail": "Too many authentication attempts"}
        assert calls == 1

    asyncio.run(exercise())
