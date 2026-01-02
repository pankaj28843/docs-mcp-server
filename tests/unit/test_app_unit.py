"""Unit-scoped tests for docs_mcp_server.app."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import signal
from types import TracebackType
from typing import Any, Self

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from docs_mcp_server.app import (
    _build_env_deployment_from_env,
    _derive_env_tenant_codename,
    create_app,
)


class FakeLifespan:
    def __init__(self, name: str, events: list[tuple[str, str]]):
        self.name = name
        self.events = events

    async def __aenter__(self) -> Self:
        self.events.append(("enter", self.name))
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.events.append(("exit", self.name))


class FakeHttpApp(Starlette):
    def __init__(self, name: str, events: list[tuple[str, str]]):
        super().__init__(
            routes=[
                Route("/health", endpoint=self._health, methods=["GET"]),
                Route("/mcp", endpoint=self._mcp, methods=["GET"]),
            ]
        )
        self.name = name
        self.events = events

    async def _health(self, _request: Any) -> JSONResponse:
        return JSONResponse({"status": "healthy", "name": self.name})

    async def _mcp(self, _request: Any) -> JSONResponse:
        return JSONResponse({"mcp": self.name})

    def lifespan(self, _app: Any) -> FakeLifespan:
        return FakeLifespan(self.name, self.events)


class FakeTenantApp:
    def __init__(self, config: Any, events: list[tuple[str, str]]):
        self.codename = config.codename
        self.docs_name = config.docs_name
        self._events = events

    async def initialize(self) -> None:
        self._events.append(("initialize", self.codename))

    async def health(self) -> dict[str, Any]:
        return {"status": "healthy", "name": self.docs_name, "documents": 0}

    async def shutdown(self) -> None:
        self._events.append(("shutdown", self.codename))


class FakeRootHub:
    def __init__(self, events: list[tuple[str, str]]):
        self._http_app = FakeHttpApp("root", events)

    def http_app(self, path: str = "/mcp") -> FakeHttpApp:
        return self._http_app


@pytest.mark.unit
def test_create_app_returns_none_on_invalid_config(tmp_path: Path) -> None:
    """Invalid deployment config should be caught and return None."""

    config_path = tmp_path / "deployment.json"
    invalid_payload = {
        "infrastructure": {},
        "tenants": [],  # Violates min_length constraint and triggers ValidationError
    }
    config_path.write_text(json.dumps(invalid_payload), encoding="utf-8")

    app = create_app(config_path)

    assert app is None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        ("Django REST", "django-rest"),
        ("123Docs", "docs-123docs"),
        ("!", "docs"),
        ("A", "ax"),
    ],
)
def test_derive_env_tenant_codename_handles_edge_cases(raw_name: str, expected: str) -> None:
    actual = _derive_env_tenant_codename(raw_name)
    assert actual == expected


@pytest.mark.unit
def test_build_env_deployment_from_env_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCS_NAME", "Space Docs")
    monkeypatch.setenv("DOCS_ENTRY_URL", "https://example.com/space")
    monkeypatch.delenv("DOCS_SITEMAP_URL", raising=False)

    config = _build_env_deployment_from_env()
    assert config.tenants[0].codename == "space-docs"
    assert config.tenants[0].docs_entry_url == "https://example.com/space"


@pytest.mark.unit
def test_build_env_deployment_requires_docs_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCS_NAME", "   ")
    monkeypatch.setenv("DOCS_ENTRY_URL", "https://example.com/fallback")

    with pytest.raises(ValueError, match="DOCS_NAME"):
        _build_env_deployment_from_env()


@pytest.mark.unit
def test_build_env_deployment_requires_entry_or_sitemap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCS_NAME", "Docs")
    monkeypatch.delenv("DOCS_ENTRY_URL", raising=False)
    monkeypatch.delenv("DOCS_SITEMAP_URL", raising=False)
    monkeypatch.setenv("DOCS_SYNC_ENABLED", "false")

    with pytest.raises(ValueError, match="DOCS_ENTRY_URL"):
        _build_env_deployment_from_env()


@pytest.fixture
def standard_config() -> dict[str, Any]:
    return {
        "infrastructure": {
            "mcp_host": "127.0.0.1",
            "mcp_port": 9000,
            "max_concurrent_requests": 5,
            "uvicorn_workers": 1,
            "uvicorn_limit_concurrency": 10,
            "log_level": "info",
            "search_include_stats": True,
            "operation_mode": "online",
            "http_timeout": 30,
            "search_timeout": 5,
            "default_snippet_surrounding_chars": 500,
            "default_fetch_mode": "full",
            "default_fetch_surrounding_chars": 200,
            "crawler_playwright_first": True,
        },
        "tenants": [
            {
                "codename": "alpha",
                "docs_name": "Alpha Docs",
                "docs_sitemap_url": "https://example.com/sitemap.xml",
                "url_whitelist_prefixes": "https://example.com/",
            }
        ],
    }


@pytest.mark.unit
def test_create_app_mounts_tenant_and_root_endpoints(
    tmp_path: Path, standard_config: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure create_app exposes health, /mcp, and mcp.json endpoints."""

    config_path = tmp_path / "deployment.json"
    config_path.write_text(json.dumps(standard_config), encoding="utf-8")
    events: list[tuple[str, str]] = []

    _install_minimal_stubs(monkeypatch, events)

    app = create_app(config_path)
    assert app is not None

    client = TestClient(app)

    # New architecture: /mcp.json returns single root server
    mcp_config = client.get("/mcp.json").json()
    assert "docs-mcp-root" in mcp_config["servers"]
    assert mcp_config["defaultModel"] == "claude-haiku-4.5"

    # New architecture: /health aggregates all tenant health
    aggregated = client.get("/health").json()
    assert aggregated["tenant_count"] == 1
    assert "tenants" in aggregated
    assert "alpha" in aggregated["tenants"]


@pytest.mark.unit
def test_create_app_env_driven_single_tenant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Env fallback should build a single tenant app exposing /mcp using DOCS_* vars."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DOCS_NAME", "Legacy Docs")
    monkeypatch.setenv("DOCS_ENTRY_URL", "https://legacy.example/docs")
    events: list[tuple[str, str]] = []

    _install_minimal_stubs(monkeypatch, events)

    app = create_app()
    assert isinstance(app, Starlette)

    # New architecture: single /mcp endpoint serves all tenants
    client = TestClient(app)
    response = client.get("/mcp.json")
    assert response.status_code == 200
    config_data = response.json()
    assert "servers" in config_data
    assert "docs-mcp-root" in config_data["servers"]
    assert config_data["defaultModel"] == "claude-haiku-4.5"


@pytest.mark.unit
def test_combined_lifespan_enters_and_exits_in_order(
    tmp_path: Path, standard_config: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify the combined lifespan context initializes tenants and handles shutdown."""

    config_path = tmp_path / "deployment.json"
    config_path.write_text(json.dumps(standard_config), encoding="utf-8")
    events: list[tuple[str, str]] = []

    _install_minimal_stubs(monkeypatch, events)

    app = create_app(config_path)
    assert app is not None

    with TestClient(app) as client:
        client.get("/health")

    # New architecture: TenantApp.initialize() is called, not lifespan context manager
    # Events should include tenant initialization and root hub lifecycle
    assert ("initialize", "alpha") in events
    assert ("enter", "root") in events


@pytest.mark.asyncio
async def test_signal_handlers_trigger_shutdown_event(
    tmp_path: Path, standard_config: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Signal hooks should register handlers that set the app shutdown event."""

    config_path = tmp_path / "deployment.json"
    config_path.write_text(json.dumps(standard_config), encoding="utf-8")
    events: list[tuple[str, str]] = []

    _install_minimal_stubs(monkeypatch, events)

    captured_handlers: dict[int, Any] = {}

    def fake_signal(sig: int, handler: Any) -> None:
        captured_handlers[sig] = handler

    monkeypatch.setattr("docs_mcp_server.app.signal.signal", fake_signal)

    app = create_app(config_path)
    assert isinstance(app, Starlette)
    assert signal.SIGTERM in captured_handlers
    assert signal.SIGINT in captured_handlers

    shutdown_event = getattr(app.state, "shutdown_event", None)
    assert isinstance(shutdown_event, asyncio.Event)
    assert not shutdown_event.is_set()

    captured_handlers[signal.SIGTERM](signal.SIGTERM, None)
    assert shutdown_event.is_set()


@pytest.mark.unit
def test_health_endpoint_handles_tenant_health_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tenant health() error should propagate into the aggregated response."""

    config_path = tmp_path / "deployment.json"
    config_payload = {
        "infrastructure": {
            "mcp_port": 8000,
            "max_concurrent_requests": 10,
        },
        "tenants": [
            {
                "codename": "alpha",
                "docs_name": "Alpha Docs",
                "docs_sitemap_url": "https://example.com/sitemap.xml",
            }
        ],
    }
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")

    class _TenantWithHealthError:
        def __init__(self, codename: str, docs_name: str):
            self.codename = codename
            self.docs_name = docs_name

        async def initialize(self) -> None:
            pass

        async def health(self) -> dict[str, Any]:
            raise RuntimeError("Health check failed")

    monkeypatch.setattr(
        "docs_mcp_server.app.create_tenant_app",
        lambda tenant_config, _, infra: _TenantWithHealthError(tenant_config.codename, tenant_config.docs_name),
    )
    monkeypatch.setattr("docs_mcp_server.app.create_root_hub", lambda *_: FakeRootHub([]))

    app = create_app(config_path)
    client = TestClient(app)
    payload = client.get("/health").json()

    assert payload["tenants"]["alpha"]["status"] == "unhealthy"
    assert "Health check failed" in payload["tenants"]["alpha"]["error"]


def _install_minimal_stubs(monkeypatch: pytest.MonkeyPatch, events: list[tuple[str, str]]) -> None:
    monkeypatch.setattr(
        "docs_mcp_server.app.create_root_hub",
        lambda *_: FakeRootHub(events),
    )
    monkeypatch.setattr("docs_mcp_server.app.create_tenant_app", lambda cfg, _, infra: FakeTenantApp(cfg, events))
