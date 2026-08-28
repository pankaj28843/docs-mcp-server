"""Unit tests for runtime utilities."""

import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from docs_mcp_server.runtime.health import build_health_endpoint, build_liveness_endpoint


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_health_endpoint_marks_degraded_when_tenant_unhealthy():
    class Tenant:
        def __init__(self, codename, docs_name, status):
            self.codename = codename
            self.docs_name = docs_name
            self._status = status

        async def health(self):
            return {"status": self._status, "tenant": self.codename}

    tenants = [Tenant("alpha", "Alpha Docs", "healthy"), Tenant("beta", "Beta Docs", "unhealthy")]
    infra = SimpleNamespace(operation_mode="online")

    health_check = build_health_endpoint(tenants, infra)
    app = SimpleNamespace(state=SimpleNamespace())
    request = Request({"type": "http", "method": "GET", "path": "/health", "headers": [], "app": app})

    response = await health_check(request)
    payload = json.loads(response.body)

    assert payload["status"] == "degraded"
    assert payload["tenants"]["beta"]["status"] == "unhealthy"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_health_endpoint_exposes_unready_browser():
    infra = SimpleNamespace(operation_mode="online")
    browser = SimpleNamespace(snapshot=lambda: {"ready": False, "state": "disconnected"})
    health_check = build_health_endpoint([], infra, browser)
    request = Request({"type": "http", "method": "GET", "path": "/health", "headers": []})

    response = await health_check(request)
    payload = json.loads(response.body)

    assert payload["status"] == "degraded"
    assert payload["infrastructure"]["browser"] == {
        "ready": False,
        "state": "disconnected",
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_liveness_endpoint_does_not_inspect_tenants():
    endpoint = build_liveness_endpoint()
    request = Request({"type": "http", "method": "GET", "path": "/healthz", "headers": []})

    response = await endpoint(request)

    assert response.status_code == 200
    assert json.loads(response.body) == {"status": "ok"}
