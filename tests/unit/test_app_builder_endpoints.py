from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

from docs_mcp_server.app_builder import AppBuilder
from docs_mcp_server.registry import TenantRegistry


class DummyScheduler:
    def __init__(self, *, init_result: bool = True, trigger_result: dict | None = None) -> None:
        self.is_initialized = False
        self.running = False
        self._init_result = init_result
        self._trigger_result = trigger_result or {"success": True, "message": "ok"}
        self.init_calls = 0
        self.trigger_calls: list[dict] = []

    async def initialize(self) -> bool:
        self.init_calls += 1
        return self._init_result

    async def trigger_sync(self, *, force_crawler: bool = False, force_full_sync: bool = False) -> dict:
        self.trigger_calls.append({"force_crawler": force_crawler, "force_full_sync": force_full_sync})
        return dict(self._trigger_result)

    async def get_status_snapshot(self) -> dict:
        return {"status": "ok"}


class DummyServices:
    def __init__(self, scheduler: DummyScheduler) -> None:
        self._scheduler = scheduler

    def get_scheduler_service(self) -> DummyScheduler:
        return self._scheduler


class DummyTenant:
    def __init__(self, codename: str, scheduler: DummyScheduler) -> None:
        self.codename = codename
        self.services = DummyServices(scheduler)


@pytest.mark.unit
def test_sync_trigger_returns_503_when_offline() -> None:
    builder = AppBuilder()
    builder.tenant_registry = TenantRegistry()

    endpoint = builder._build_sync_trigger_endpoint(operation_mode="offline")
    app = Starlette(routes=[Route("/{tenant}/sync/trigger", endpoint=endpoint, methods=["POST"])])

    client = TestClient(app)
    response = client.post("/demo/sync/trigger")

    assert response.status_code == 503
    assert response.json()["message"] == "Sync trigger only available in online mode"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sync_trigger_missing_tenant_returns_400() -> None:
    builder = AppBuilder()
    builder.tenant_registry = TenantRegistry()

    endpoint = builder._build_sync_trigger_endpoint(operation_mode="online")
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/sync/trigger",
        "headers": [],
        "query_string": b"",
        "path_params": {},
    }
    request = Request(scope)

    response = await endpoint(request)
    assert response.status_code == 400
    assert response.body


@pytest.mark.unit
def test_sync_trigger_unknown_tenant_returns_404() -> None:
    builder = AppBuilder()
    builder.tenant_registry = TenantRegistry()

    scheduler = DummyScheduler()
    tenant = DummyTenant("alpha", scheduler)
    builder.tenant_registry.register(SimpleNamespace(codename="alpha"), tenant)

    endpoint = builder._build_sync_trigger_endpoint(operation_mode="online")
    app = Starlette(routes=[Route("/{tenant}/sync/trigger", endpoint=endpoint, methods=["POST"])])

    client = TestClient(app)
    response = client.post("/beta/sync/trigger")

    assert response.status_code == 404
    assert "Available" in response.json()["message"]


@pytest.mark.unit
def test_sync_trigger_initialization_failure_returns_503() -> None:
    builder = AppBuilder()
    builder.tenant_registry = TenantRegistry()

    scheduler = DummyScheduler(init_result=False)
    tenant = DummyTenant("alpha", scheduler)
    builder.tenant_registry.register(SimpleNamespace(codename="alpha"), tenant)

    endpoint = builder._build_sync_trigger_endpoint(operation_mode="online")
    app = Starlette(routes=[Route("/{tenant}/sync/trigger", endpoint=endpoint, methods=["POST"])])

    client = TestClient(app)
    response = client.post("/alpha/sync/trigger")

    assert response.status_code == 503
    assert response.json()["message"] == "Failed to initialize scheduler for this tenant"


@pytest.mark.unit
def test_sync_trigger_passes_force_flags() -> None:
    builder = AppBuilder()
    builder.tenant_registry = TenantRegistry()

    scheduler = DummyScheduler()
    scheduler.is_initialized = True
    tenant = DummyTenant("alpha", scheduler)
    builder.tenant_registry.register(SimpleNamespace(codename="alpha"), tenant)

    endpoint = builder._build_sync_trigger_endpoint(operation_mode="online")
    app = Starlette(routes=[Route("/{tenant}/sync/trigger", endpoint=endpoint, methods=["POST"])])

    client = TestClient(app)
    response = client.post("/alpha/sync/trigger?force_crawler=true&force_full_sync=true")

    assert response.status_code == 200
    assert scheduler.trigger_calls == [{"force_crawler": True, "force_full_sync": True}]


@pytest.mark.unit
def test_sync_status_returns_scheduler_snapshot() -> None:
    builder = AppBuilder()
    builder.tenant_registry = TenantRegistry()

    scheduler = DummyScheduler()
    scheduler.is_initialized = True
    scheduler.running = True
    tenant = DummyTenant("alpha", scheduler)
    builder.tenant_registry.register(SimpleNamespace(codename="alpha"), tenant)

    endpoint = builder._build_sync_status_endpoint()
    app = Starlette(routes=[Route("/{tenant}/sync/status", endpoint=endpoint, methods=["GET"])])

    client = TestClient(app)
    response = client.get("/alpha/sync/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant"] == "alpha"
    assert payload["scheduler_running"] is True
    assert payload["scheduler_initialized"] is True
    assert payload["stats"] == {"status": "ok"}
