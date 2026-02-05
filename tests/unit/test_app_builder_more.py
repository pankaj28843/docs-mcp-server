"""Additional unit tests for AppBuilder edge cases."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.applications import Starlette

from docs_mcp_server.app_builder import (
    AppBuilder,
    _exit_process,
    _handle_critical_database_error,
)
from docs_mcp_server.utils.crawl_state_store import DatabaseCriticalError


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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_critical_database_error_returns_503() -> None:
    """Exception handler returns 503 with correct JSON structure."""
    # Create a mock request
    mock_request = MagicMock()

    # Create exception
    exc = DatabaseCriticalError("test database error")

    # Mock the loop to avoid actually scheduling exit
    mock_loop = MagicMock()
    with patch("asyncio.get_running_loop", return_value=mock_loop):
        response = await _handle_critical_database_error(mock_request, exc)

    assert response.status_code == 503

    body = json.loads(response.body)
    assert body["error"] == "database_critical_error"
    assert "test database error" in body["detail"]
    assert body["action"] == "container_restarting"

    # Verify exit was scheduled
    mock_loop.call_later.assert_called_once()
    call_args = mock_loop.call_later.call_args
    assert call_args[0][0] == 0.5  # delay


@pytest.mark.unit
def test_exit_process_calls_os_exit() -> None:
    """_exit_process calls os._exit(1) to trigger container restart."""
    with patch("os._exit") as mock_exit:
        _exit_process()

    mock_exit.assert_called_once_with(1)


@pytest.mark.unit
def test_database_critical_error_handler_registered_in_app(tmp_path: Path) -> None:
    """DatabaseCriticalError exception handler is registered in Starlette app."""
    # Create minimal deployment config
    config_path = tmp_path / "deployment.json"
    config_path.write_text(
        json.dumps(
            {
                "infrastructure": {"mcp_port": 9999},
                "tenants": [
                    {
                        "codename": "test",
                        "docs_name": "Test",
                        "source_type": "filesystem",
                        "docs_root_dir": str(tmp_path / "docs"),
                    }
                ],
            }
        )
    )
    (tmp_path / "docs").mkdir()

    builder = AppBuilder(config_path=config_path)
    app = builder.build()

    assert app is not None
    # Verify exception handler is registered
    assert DatabaseCriticalError in app.exception_handlers
