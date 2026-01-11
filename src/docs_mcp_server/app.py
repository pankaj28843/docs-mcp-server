"""Starlette entrypoint that delegates to :class:`AppBuilder`."""

from __future__ import annotations

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


def create_app(config_path: Path | None = None) -> Starlette | None:
    """Create the ASGI application using :class:`AppBuilder`."""

    builder = AppBuilder(config_path)
    return builder.build()


def main() -> None:
    """Main entry point for multi-tenant server."""
    # Load config path from environment or use default
    config_path_str = os.getenv("DEPLOYMENT_CONFIG", "deployment.json")
    config_path = Path(config_path_str)

    # Load deployment config to get server settings
    try:
        deployment_config = DeploymentConfig.from_json_file(config_path)
    except ValidationError as exc:
        logger.error("Deployment configuration is invalid: %s", exc)
        return
    infra = deployment_config.infrastructure

    # Configure logging
    log_level_str = infra.log_level.upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True,
    )

    # Configure key loggers
    for logger_name in ["docs_mcp_server", "uvicorn", "uvicorn.error", "uvicorn.access"]:
        logging.getLogger(logger_name).setLevel(log_level)

    mcp_log_level = logging.DEBUG if log_level == logging.DEBUG else logging.WARNING
    for logger_name in [
        "fastmcp",
        "mcp",
        "mcp.server",
        "mcp.server.lowlevel",
        "mcp.server.streamable_http",
        "mcp.server.streamable_http_manager",
    ]:
        logging.getLogger(logger_name).setLevel(mcp_log_level)

    logger.info("=" * 80)
    logger.info("Starting Docs MCP Server")
    logger.info("Configuration: %s", config_path)
    logger.info("Tenants: %d", len(deployment_config.tenants))
    logger.info("=" * 80)

    # Create app
    app = create_app(config_path)
    if app is None:
        logger.error("Unable to start server due to invalid configuration")
        return

    # Run server
    host = infra.mcp_host
    port = infra.mcp_port

    logger.info("Starting server on %s:%d", host, port)
    logger.info("Health check: http://%s:%d/health", host, port)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=infra.log_level.lower(),
        log_config=None,  # Don't let uvicorn override our logging config
        workers=infra.uvicorn_workers,
        limit_concurrency=infra.uvicorn_limit_concurrency,
        access_log=infra.log_level.lower() == "debug",
    )


if __name__ == "__main__":
    main()
