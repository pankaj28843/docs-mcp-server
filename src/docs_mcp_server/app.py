"""Starlette entrypoint that delegates to :class:`AppBuilder`."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError
import uvicorn

from .app_builder import (
    AppBuilder,
    _build_env_deployment_from_env as _builder_env_config,
    _derive_env_tenant_codename as _builder_tenant_slug,
)
from .deployment_config import DeploymentConfig
from .root_hub import create_root_hub as _create_root_hub
from .tenant import create_tenant_app as _create_tenant_app


if TYPE_CHECKING:
    from starlette.applications import Starlette


logger = logging.getLogger(__name__)

_build_env_deployment_from_env = _builder_env_config
_derive_env_tenant_codename = _builder_tenant_slug
create_root_hub = _create_root_hub
create_tenant_app = _create_tenant_app


@dataclass(frozen=True)
class ServerRuntimeConfig:
    """Resolved runtime configuration used by the process entrypoint."""

    config_path: Path
    deployment: DeploymentConfig
    host: str
    port: int
    log_level_name: str
    log_level_value: int


def create_app(config_path: Path | None = None) -> Starlette | None:
    """Create the ASGI application using :class:`AppBuilder`."""

    builder = AppBuilder(config_path)
    return builder.build()


def _resolve_config_path() -> Path:
    config_path_str = os.getenv("DEPLOYMENT_CONFIG", "deployment.json")
    return Path(config_path_str)


def _resolve_log_level(log_level: str) -> tuple[str, int]:
    log_level_name = log_level.upper()
    log_level_value = getattr(logging, log_level_name, logging.INFO)
    return log_level_name, log_level_value


def _load_runtime_config(config_path: Path) -> ServerRuntimeConfig:
    deployment = DeploymentConfig.from_json_file(config_path)
    infra = deployment.infrastructure
    log_level_name, log_level_value = _resolve_log_level(infra.log_level)
    return ServerRuntimeConfig(
        config_path=config_path,
        deployment=deployment,
        host=infra.mcp_host,
        port=infra.mcp_port,
        log_level_name=log_level_name,
        log_level_value=log_level_value,
    )


def _configure_process_logging(runtime: ServerRuntimeConfig) -> None:
    logging.basicConfig(
        level=runtime.log_level_value,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True,
    )
    for logger_name in ["docs_mcp_server", "uvicorn", "uvicorn.error", "uvicorn.access"]:
        logging.getLogger(logger_name).setLevel(runtime.log_level_value)

    mcp_log_level = logging.DEBUG if runtime.log_level_value == logging.DEBUG else logging.WARNING
    for logger_name in [
        "fastmcp",
        "mcp",
        "mcp.server",
        "mcp.server.lowlevel",
        "mcp.server.streamable_http",
        "mcp.server.streamable_http_manager",
    ]:
        logging.getLogger(logger_name).setLevel(mcp_log_level)


def _log_startup(runtime: ServerRuntimeConfig) -> None:
    logger.info("=" * 80)
    logger.info("Starting Docs MCP Server")
    logger.info("Configuration: %s", runtime.config_path)
    logger.info("Tenants: %d", len(runtime.deployment.tenants))
    logger.info("=" * 80)
    logger.info("Starting server on %s:%d", runtime.host, runtime.port)
    logger.info("Health check: http://%s:%d/health", runtime.host, runtime.port)


def _run_uvicorn(app: Starlette, runtime: ServerRuntimeConfig) -> None:
    infra = runtime.deployment.infrastructure
    uvicorn.run(
        app,
        host=runtime.host,
        port=runtime.port,
        log_level=infra.log_level.lower(),
        log_config=None,
        workers=infra.uvicorn_workers,
        limit_concurrency=infra.uvicorn_limit_concurrency,
        access_log=infra.log_level.lower() == "debug",
    )


def load_runtime_config(config_path: Path | None = None) -> ServerRuntimeConfig:
    """Resolve and load process runtime configuration for server startup."""

    resolved_path = config_path if config_path is not None else _resolve_config_path()
    return _load_runtime_config(resolved_path)


def main() -> None:
    """Main entry point for multi-tenant server."""
    try:
        runtime = load_runtime_config()
    except ValidationError as exc:
        logger.error("Deployment configuration is invalid: %s", exc)
        return
    _configure_process_logging(runtime)
    _log_startup(runtime)

    app = create_app(runtime.config_path)
    if app is None:
        logger.error("Unable to start server due to invalid configuration")
        return

    _run_uvicorn(app, runtime)


if __name__ == "__main__":
    main()
