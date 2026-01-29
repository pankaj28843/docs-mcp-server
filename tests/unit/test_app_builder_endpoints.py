from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

from docs_mcp_server.app_builder import AppBuilder
from docs_mcp_server.deployment_config import DeploymentConfig, SharedInfraConfig, TenantConfig
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
        return {
            "scheduler_running": self.running,
            "scheduler_initialized": self.is_initialized,
            "stats": {"status": "ok"},
        }


class DummySyncRuntime:
    def __init__(self, scheduler: DummyScheduler) -> None:
        self._scheduler = scheduler

    def get_scheduler_service(self) -> DummyScheduler:
        return self._scheduler


class DummyTenant:
    def __init__(self, codename: str, scheduler: DummyScheduler) -> None:
        self.codename = codename
        self.sync_runtime = DummySyncRuntime(scheduler)


class DummyMetadataStore:
    async def get_event_history(
        self,
        *,
        range_days: int | None,
        minutes: int,
        bucket_seconds: int,
        limit: int,
    ) -> dict:
        return {
            "ok": True,
            "range_days": range_days,
            "minutes": minutes,
            "bucket_seconds": bucket_seconds,
            "limit": limit,
        }

    async def get_event_log(
        self,
        *,
        event_type: str | None,
        status: str | None,
        limit: int,
    ) -> dict:
        return {
            "ok": True,
            "event_type": event_type,
            "status": status,
            "limit": limit,
        }


def _dashboard_builder_with_metadata(metadata_store: DummyMetadataStore | None) -> AppBuilder:
    builder = AppBuilder()
    builder.tenant_registry = TenantRegistry()
    scheduler = DummyScheduler()
    scheduler.metadata_store = metadata_store
    tenant = DummyTenant("alpha", scheduler)
    builder.tenant_registry.register(SimpleNamespace(codename="alpha"), tenant)
    builder.tenant_configs_map["alpha"] = SimpleNamespace(source_type="online")
    return builder


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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sync_status_missing_tenant_returns_400() -> None:
    builder = AppBuilder()
    builder.tenant_registry = TenantRegistry()

    endpoint = builder._build_sync_status_endpoint()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/sync/status",
        "headers": [],
        "query_string": b"",
        "path_params": {},
    }
    request = Request(scope)

    response = await endpoint(request)

    assert response.status_code == 400


@pytest.mark.unit
def test_sync_status_unknown_tenant_returns_404() -> None:
    builder = AppBuilder()
    builder.tenant_registry = TenantRegistry()

    scheduler = DummyScheduler()
    tenant = DummyTenant("alpha", scheduler)
    builder.tenant_registry.register(SimpleNamespace(codename="alpha"), tenant)

    endpoint = builder._build_sync_status_endpoint()
    app = Starlette(routes=[Route("/{tenant}/sync/status", endpoint=endpoint, methods=["GET"])])

    client = TestClient(app)
    response = client.get("/beta/sync/status")

    assert response.status_code == 404
    assert "Available" in response.json()["message"]


@pytest.mark.unit
def test_dashboard_offline_returns_503() -> None:
    builder = AppBuilder()
    builder.tenant_registry = TenantRegistry()

    endpoint = builder._build_dashboard_endpoint(operation_mode="offline")
    app = Starlette(routes=[Route("/dashboard", endpoint=endpoint, methods=["GET"])])

    client = TestClient(app)
    response = client.get("/dashboard")

    assert response.status_code == 503
    assert "Dashboard is only available in online mode" in response.text


@pytest.mark.unit
def test_dashboard_online_returns_html() -> None:
    builder = AppBuilder()
    builder.tenant_registry = TenantRegistry()
    builder.tenant_registry.register(SimpleNamespace(codename="alpha"), DummyTenant("alpha", DummyScheduler()))
    builder.tenant_configs_map["alpha"] = SimpleNamespace(source_type="online")

    endpoint = builder._build_dashboard_endpoint(operation_mode="online")
    app = Starlette(routes=[Route("/dashboard", endpoint=endpoint, methods=["GET"])])

    client = TestClient(app)
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Tenant Crawl Dashboard" in response.text
    assert "@tailwindcss/browser@4" in response.text
    assert "chart.js" in response.text


@pytest.mark.unit
def test_dashboard_tenant_requires_allowed_tenant() -> None:
    builder = AppBuilder()
    builder.tenant_registry = TenantRegistry()
    builder.tenant_registry.register(SimpleNamespace(codename="alpha"), DummyTenant("alpha", DummyScheduler()))
    builder.tenant_configs_map["alpha"] = SimpleNamespace(source_type="filesystem")

    endpoint = builder._build_dashboard_tenant_endpoint(operation_mode="online")
    app = Starlette(routes=[Route("/dashboard/{tenant}", endpoint=endpoint, methods=["GET"])])

    client = TestClient(app)
    response = client.get("/dashboard/alpha")

    assert response.status_code == 404


@pytest.mark.unit
def test_dashboard_events_rejects_invalid_params() -> None:
    builder = _dashboard_builder_with_metadata(DummyMetadataStore())
    endpoint = builder._build_dashboard_events_endpoint(operation_mode="online")
    app = Starlette(routes=[Route("/dashboard/{tenant}/events", endpoint=endpoint, methods=["GET"])])
    client = TestClient(app)

    response = client.get("/dashboard/alpha/events?range_days=0")
    assert response.status_code == 400

    response = client.get("/dashboard/alpha/events?bucket_minutes=0")
    assert response.status_code == 400

    response = client.get("/dashboard/alpha/events?limit=99999")
    assert response.status_code == 400


@pytest.mark.unit
def test_dashboard_events_requires_metadata_store() -> None:
    builder = _dashboard_builder_with_metadata(None)
    endpoint = builder._build_dashboard_events_endpoint(operation_mode="online")
    app = Starlette(routes=[Route("/dashboard/{tenant}/events", endpoint=endpoint, methods=["GET"])])
    client = TestClient(app)

    response = client.get("/dashboard/alpha/events")
    assert response.status_code == 404


@pytest.mark.unit
def test_dashboard_events_returns_payload() -> None:
    builder = _dashboard_builder_with_metadata(DummyMetadataStore())
    endpoint = builder._build_dashboard_events_endpoint(operation_mode="online")
    app = Starlette(routes=[Route("/dashboard/{tenant}/events", endpoint=endpoint, methods=["GET"])])
    client = TestClient(app)

    response = client.get("/dashboard/alpha/events?range_days=7&bucket_minutes=60&limit=10")
    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["range_days"] == 7
    assert payload["bucket_seconds"] == 3600
    assert payload["limit"] == 10


@pytest.mark.unit
def test_dashboard_event_logs_validates_limit() -> None:
    builder = _dashboard_builder_with_metadata(DummyMetadataStore())
    endpoint = builder._build_dashboard_event_logs_endpoint(operation_mode="online")
    app = Starlette(routes=[Route("/dashboard/{tenant}/events/logs", endpoint=endpoint, methods=["GET"])])
    client = TestClient(app)

    response = client.get("/dashboard/alpha/events/logs?limit=not-a-number")
    assert response.status_code == 400

    response = client.get("/dashboard/alpha/events/logs?limit=500")
    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["limit"] == 500


@pytest.mark.unit
@pytest.mark.asyncio
async def test_metrics_endpoint_returns_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    builder = AppBuilder()

    monkeypatch.setattr("docs_mcp_server.app_builder.get_metrics", lambda: "metrics")
    monkeypatch.setattr("docs_mcp_server.app_builder.get_metrics_content_type", lambda: "text/plain")

    endpoint = builder._build_metrics_endpoint()
    scope = {"type": "http", "method": "GET", "path": "/metrics", "headers": [], "query_string": b""}
    request = Request(scope)

    response = await endpoint(request)

    assert response.status_code == 200
    assert response.body == b"metrics"


@pytest.mark.unit
def test_app_builder_uses_log_profile_from_config() -> None:
    """Test that AppBuilder retrieves and applies active log profile settings."""
    config = DeploymentConfig(
        infrastructure=SharedInfraConfig(
            log_profile="custom-debug",
            log_profiles={
                "custom-debug": {
                    "level": "debug",
                    "json_output": False,
                    "trace_categories": ["docs_mcp_server"],
                    "trace_level": "debug",
                    "logger_levels": {"uvicorn.access": "warning"},
                    "access_log": True,
                },
            },
        ),
        tenants=[
            TenantConfig(
                source_type="filesystem",
                codename="test",
                docs_name="Test",
                docs_root_dir="./mcp-data/test",
            ),
        ],
    )

    with (
        patch("docs_mcp_server.app_builder.configure_logging") as mock_logging,
        patch("docs_mcp_server.app_builder.init_tracing"),
        patch("docs_mcp_server.app_builder.SqliteSegmentStore"),
    ):
        builder = AppBuilder()
        # Mock _load_config to return our test config
        builder._load_config = MagicMock(return_value=(config, False))
        builder._initialize_tenants = MagicMock()
        builder._build_routes = MagicMock(return_value=[])
        builder._build_lifespan_manager = MagicMock(return_value=None)

        # Trigger the build method to exercise log profile retrieval
        builder.build()

        # Verify configure_logging was called with profile settings
        mock_logging.assert_called_once()
        call_kwargs = mock_logging.call_args.kwargs
        assert call_kwargs["level"] == "debug"
        assert call_kwargs["json_output"] is False
        assert call_kwargs["trace_categories"] == ["docs_mcp_server"]
        assert call_kwargs["trace_level"] == "debug"
        assert call_kwargs["logger_levels"] == {"uvicorn.access": "warning"}
        assert call_kwargs["access_log"] is True
