"""Unit tests for runtime utilities."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from docs_mcp_server.runtime.health import build_health_endpoint
from docs_mcp_server.runtime.signals import install_shutdown_signals


@pytest.mark.unit
def test_install_shutdown_signals_reuses_existing_event():
    app = SimpleNamespace(state=SimpleNamespace(shutdown_event=asyncio.Event()))

    event = install_shutdown_signals(app)

    assert event is app.state.shutdown_event


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
