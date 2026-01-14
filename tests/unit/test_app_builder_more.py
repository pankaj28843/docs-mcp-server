"""Additional unit tests for AppBuilder edge cases."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from starlette.applications import Starlette

from docs_mcp_server.app_builder import AppBuilder


@pytest.mark.unit
def test_load_config_raises_when_env_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder = AppBuilder(config_path=tmp_path / "missing.json")

    def _boom():
        raise ValueError("boom")

    monkeypatch.setattr("docs_mcp_server.app_builder._build_env_deployment_from_env", _boom)

    with pytest.raises(FileNotFoundError):
        builder._load_config()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lifespan_drains_on_shutdown_event() -> None:
    builder = AppBuilder()

    class DummyTenant:
        def __init__(self) -> None:
            self.init_calls = 0
            self.shutdown_calls = 0

        async def initialize(self) -> None:
            self.init_calls += 1

        async def shutdown(self) -> None:
            self.shutdown_calls += 1

    class DummyRootHub:
        def lifespan(self, _app):
            @asynccontextmanager
            async def _ctx():
                yield

            return _ctx()

    class DummyAudit:
        def schedule(self):
            return asyncio.create_task(asyncio.sleep(0))

        def cancel(self):
            return None

    tenant = DummyTenant()
    builder.tenant_apps = [tenant]
    builder.root_hub_http_app = DummyRootHub()
    builder.boot_audit_service = DummyAudit()
    builder.env_driven_config = False

    lifespan = builder._build_lifespan_manager()
    app = Starlette()
    app.state.shutdown_event = asyncio.Event()

    async with lifespan(app):
        app.state.shutdown_event.set()
        await asyncio.sleep(0)

    assert tenant.init_calls == 1
    assert tenant.shutdown_calls == 1
