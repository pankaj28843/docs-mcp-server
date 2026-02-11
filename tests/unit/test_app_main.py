"""Unit tests for app entrypoint helpers."""

from __future__ import annotations

import json
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


def test_resolve_config_path_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_CONFIG", "/tmp/custom-deployment.json")
    resolved = app_module._resolve_config_path()
    assert str(resolved) == "/tmp/custom-deployment.json"


def test_load_runtime_config_maps_infra_fields(tmp_path) -> None:
    config = {
        "infrastructure": {
            "mcp_host": "0.0.0.0",
            "mcp_port": 4242,
            "log_level": "debug",
            "uvicorn_workers": 2,
            "uvicorn_limit_concurrency": 80,
        },
        "tenants": [
            {
                "source_type": "filesystem",
                "codename": "demo",
                "docs_name": "Demo Docs",
                "docs_root_dir": "./test-docs",
            }
        ],
    }
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    runtime = app_module._load_runtime_config(path)

    assert runtime.config_path == path
    assert runtime.host == "0.0.0.0"
    assert runtime.port == 4242
    assert runtime.log_level_name == "DEBUG"
    assert runtime.log_level_value > 0


def test_resolve_log_level_defaults_to_info() -> None:
    name, value = app_module._resolve_log_level("not-a-level")
    assert name == "NOT-A-LEVEL"
    assert value == app_module.logging.INFO


def test_load_runtime_config_uses_explicit_path(tmp_path) -> None:
    config = {
        "infrastructure": {
            "mcp_host": "127.0.0.1",
            "mcp_port": 42042,
            "log_level": "info",
            "uvicorn_workers": 1,
            "uvicorn_limit_concurrency": 100,
        },
        "tenants": [
            {
                "source_type": "filesystem",
                "codename": "demo",
                "docs_name": "Demo Docs",
                "docs_root_dir": "./test-docs",
            }
        ],
    }
    path = tmp_path / "deployment-alt.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    runtime = app_module.load_runtime_config(path)

    assert runtime.config_path == path
    assert runtime.host == "127.0.0.1"
    assert runtime.port == 42042


def test_load_runtime_config_falls_back_to_env_when_file_missing(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(app_module, "_build_env_deployment_from_env", _deployment_config)

    runtime = app_module.load_runtime_config(missing)

    assert runtime.config_path == missing
    assert runtime.host == "127.0.0.1"
    assert runtime.port == 9000


def test_load_runtime_config_missing_file_without_env_raises_file_not_found(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(
        app_module,
        "_build_env_deployment_from_env",
        lambda: (_ for _ in ()).throw(ValueError("missing DOCS_NAME")),
    )

    with pytest.raises(FileNotFoundError):
        app_module.load_runtime_config(missing)
