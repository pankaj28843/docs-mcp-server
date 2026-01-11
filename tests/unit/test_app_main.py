"""Unit tests for app entrypoint helpers."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

import docs_mcp_server.app as app_module
from docs_mcp_server.deployment_config import DeploymentConfig, SharedInfraConfig, TenantConfig


pytestmark = pytest.mark.unit


def _deployment_config() -> DeploymentConfig:
    tenant = TenantConfig(
        source_type="filesystem",
        codename="docs",
        docs_name="Docs",
        docs_root_dir="/tmp/docs",
    )
    infra = SharedInfraConfig(
        mcp_host="127.0.0.1",
        mcp_port=9000,
        log_level="info",
        uvicorn_workers=1,
        uvicorn_limit_concurrency=123,
    )
    return DeploymentConfig(infrastructure=infra, tenants=[tenant])


def test_main_exits_on_invalid_config(monkeypatch) -> None:
    def _raise(_path):
        raise ValidationError.from_exception_data("DeploymentConfig", [])

    monkeypatch.setattr(app_module.DeploymentConfig, "from_json_file", _raise)

    app_module.main()


def test_main_skips_uvicorn_when_app_is_none(monkeypatch) -> None:
    config = _deployment_config()
    monkeypatch.setattr(app_module.DeploymentConfig, "from_json_file", lambda _path: config)
    monkeypatch.setattr(app_module, "create_app", lambda _path=None: None)

    uvicorn_stub = SimpleNamespace(run=lambda *args, **kwargs: pytest.fail("uvicorn.run should not be called"))
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn_stub)

    app_module.main()


def test_main_invokes_uvicorn_with_infra_settings(monkeypatch) -> None:
    config = _deployment_config()
    monkeypatch.setattr(app_module.DeploymentConfig, "from_json_file", lambda _path: config)
    monkeypatch.setattr(app_module, "create_app", lambda _path=None: object())

    calls = []

    def _run(app, **kwargs):
        calls.append((app, kwargs))

    monkeypatch.setattr("uvicorn.run", _run)

    app_module.main()

    assert calls
    _app, kwargs = calls[0]
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 9000
    assert kwargs["log_level"] == "info"
    assert kwargs["log_config"] is None
    assert kwargs["workers"] == 1
    assert kwargs["limit_concurrency"] == 123
