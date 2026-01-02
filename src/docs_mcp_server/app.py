"""Main ASGI application entry point.

This module creates the main ASGI application that mounts multiple
tenant FastMCP instances under different paths.

Architecture:
    Starlette App (Main Router)
      ├── /django/mcp → Django Docs MCP
      ├── /drf/mcp → DRF Docs MCP
      ├── /fastapi/mcp → FastAPI Docs MCP
      └── ... (other tenants)

Each tenant is completely isolated with its own services
and configuration.

Usage:
    # Load from deployment.json
    python -m docs_mcp_server.app

    # Or specify custom config file
    DEPLOYMENT_CONFIG=/path/to/config.json python -m docs_mcp_server.app
"""

import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import os
from pathlib import Path
import re
import signal
from typing import Literal

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from docs_mcp_server.search.storage import JsonSegmentStore

# Note: Don't import Settings here - it loads global config from env vars
# Deployment mode uses DeploymentConfig instead
from .deployment_config import DeploymentConfig
from .registry import TenantRegistry
from .root_hub import create_root_hub
from .service_layer.boot_audit_service import BootAuditService
from .tenant import create_tenant_app


logger = logging.getLogger(__name__)


def _derive_env_tenant_codename(name: str) -> str:
    """Generate a valid tenant codename from a human-readable docs name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        slug = "docs"
    if not slug[0].isalpha():
        slug = f"docs-{slug}"
    if len(slug) < 2:
        slug = slug.ljust(2, "x")
    return slug[:64]


def _build_env_deployment_from_env() -> DeploymentConfig:
    """Create a minimal DeploymentConfig from environment variables for single-tenant mode."""

    from .config import Settings

    settings = Settings()
    docs_name = settings.docs_name.strip()
    if not docs_name:
        raise ValueError("DOCS_NAME must be set for env-driven single tenant mode.")

    if not settings.get_docs_entry_urls() and not settings.get_docs_sitemap_urls():
        raise ValueError("DOCS_ENTRY_URL or DOCS_SITEMAP_URL must be provided when running without deployment.json.")

    tenant_payload = {
        "codename": _derive_env_tenant_codename(docs_name),
        "docs_name": docs_name,
        "docs_entry_url": settings.docs_entry_url,
        "docs_sitemap_url": settings.docs_sitemap_url,
        "url_whitelist_prefixes": settings.url_whitelist_prefixes,
        "url_blacklist_prefixes": settings.url_blacklist_prefixes,
    }

    infra_payload = {
        "mcp_host": settings.mcp_host,
        "mcp_port": settings.mcp_port,
        "max_concurrent_requests": settings.max_concurrent_requests,
        "uvicorn_limit_concurrency": settings.uvicorn_limit_concurrency,
        "log_level": settings.log_level,
        "operation_mode": settings.operation_mode,
        "http_timeout": settings.http_timeout,
        "crawler_playwright_first": settings.crawler_playwright_first,
        "search_max_segments": 32,
    }

    return DeploymentConfig(
        infrastructure=infra_payload,
        tenants=[tenant_payload],
    )


def _register_signal_handlers(app: Starlette) -> None:
    """Register SIGINT/SIGTERM handlers that set an asyncio.Event on the app."""

    shutdown_event = asyncio.Event()

    def _handle_shutdown(signum: int, frame: object | None) -> None:
        if shutdown_event.is_set():
            return
        name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info("Received %s signal, scheduling shutdown", name)
        shutdown_event.set()

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)
    app.state.shutdown_event = shutdown_event


def create_app(config_path: Path | None = None) -> Starlette | None:
    """Create ASGI application.

    Args:
        config_path: Path to deployment.json (defaults to ./deployment.json)

    Returns:
        Starlette application with all tenants mounted
    """
    # Load deployment configuration
    if config_path is None:
        config_path = Path("deployment.json")

    env_driven_config = False
    if not config_path.exists():
        logger.info(
            "Deployment config %s not found, attempting environment-driven single-tenant mode",
            config_path,
        )
        try:
            deployment_config = _build_env_deployment_from_env()
        except (ValidationError, ValueError) as exc:
            logger.error("Environment-driven deployment configuration failed: %s", exc)
            raise FileNotFoundError(
                f"Deployment config not found: {config_path}\n"
                f"Please create a deployment.json file or provide DOCS_* environment variables for single-tenant mode."
            ) from exc
        else:
            tenant_code = deployment_config.tenants[0].codename if deployment_config.tenants else "unknown"
            logger.info("Using env-driven deployment for tenant: %s", tenant_code)
            env_driven_config = True
    else:
        logger.info("Loading deployment configuration from %s", config_path)
        try:
            deployment_config = DeploymentConfig.from_json_file(config_path)
        except ValidationError as exc:
            logger.error("Deployment configuration is invalid: %s", exc)
            return None

    # Import Settings only when needed (after deployment config is loaded)
    # This avoids triggering env var validation in multi-tenant mode

    # Create shared Settings from infrastructure config
    infra = deployment_config.infrastructure
    JsonSegmentStore.set_max_segments(infra.search_max_segments)
    # Cast operation_mode to Literal type for Settings
    operation_mode: Literal["online", "offline"] = "online" if infra.operation_mode == "online" else "offline"
    # No longer needed to synthesize shared_config - infrastructure is embedded in tenant_config
    active_tenants = deployment_config.tenants
    logger.info("Serving %d tenants", len(active_tenants))

    if not active_tenants:
        logger.warning("No tenants configured; only shared endpoints will respond.")

    # Create tenant applications
    logger.info("Creating %d tenant applications", len(active_tenants))
    tenant_apps = []
    tenant_configs_map = {}
    routes: list[Route | Mount] = []

    for tenant_config in active_tenants:
        logger.info("Initializing tenant: %s (%s)", tenant_config.codename, tenant_config.docs_name)

        # Create tenant app (infrastructure embedded in tenant_config via Context Object pattern)
        tenant_app = create_tenant_app(tenant_config)
        tenant_apps.append(tenant_app)
        tenant_configs_map[tenant_config.codename] = tenant_config

    # Create root hub aggregator (provides discovery and proxy tools)
    logger.info("Creating root hub aggregator")
    tenant_registry = TenantRegistry()
    for tenant_app in tenant_apps:
        tenant_registry.register(tenant_configs_map[tenant_app.codename], tenant_app)
    root_hub = create_root_hub(tenant_registry)
    # path="/" ensures MCP endpoint is at /mcp/ (not /mcp/mcp/)
    root_hub_http_app = root_hub.http_app(path="/")
    routes.append(Mount("/mcp", app=root_hub_http_app))
    logger.info("Mounted Root Hub at /mcp")

    boot_audit_service = BootAuditService(config_path=config_path, tenant_count=len(active_tenants))

    # Create combined lifespan that manages all tenant lifespans
    @asynccontextmanager
    async def combined_lifespan(app: Starlette):
        """Initialize tenant services plus FastMCP apps before serving traffic."""

        app.state.boot_audit_service = boot_audit_service

        await asyncio.gather(*(tenant.initialize() for tenant in tenant_apps))

        contexts = []
        ctx = root_hub_http_app.lifespan(app)
        contexts.append(ctx)
        await ctx.__aenter__()

        boot_audit_task: asyncio.Task | None = None

        if not env_driven_config:
            boot_audit_task = boot_audit_service.schedule()

        drained = False

        async def drain(reason: str) -> None:
            nonlocal drained
            if drained:
                return
            drained = True
            logger.info("Draining tenant residency (%s)", reason)
            await asyncio.gather(
                *(tenant.shutdown() for tenant in tenant_apps),
                return_exceptions=True,
            )

        shutdown_monitor: asyncio.Task | None = None
        shutdown_event = getattr(app.state, "shutdown_event", None)
        if isinstance(shutdown_event, asyncio.Event):

            async def watch_shutdown() -> None:
                await shutdown_event.wait()
                await drain("signal")

            shutdown_monitor = asyncio.create_task(watch_shutdown())

        try:
            yield
        finally:
            if boot_audit_task is not None and not boot_audit_task.done():
                boot_audit_service.cancel()
                with suppress(asyncio.CancelledError):
                    await boot_audit_task
            if shutdown_monitor is not None:
                shutdown_monitor.cancel()
                with suppress(asyncio.CancelledError):
                    await shutdown_monitor
            await drain("lifespan-exit")
            for ctx in reversed(contexts):
                try:
                    await ctx.__aexit__(None, None, None)
                except Exception as e:
                    logger.error("Error during lifespan cleanup: %s", e, exc_info=True)

    # Add health check endpoint
    async def health_check(request: Request) -> JSONResponse:
        """Health check endpoint that aggregates all tenant and group health checks."""

        tenant_health = {}
        all_healthy = True

        boot_audit_state = None
        boot_audit = getattr(request.app.state, "boot_audit_service", None)
        if boot_audit is not None:
            boot_audit_state = boot_audit.get_status().to_dict()

        for tenant_app in tenant_apps:
            try:
                tenant_health[tenant_app.codename] = await tenant_app.health()
                if tenant_health[tenant_app.codename]["status"] != "healthy":
                    all_healthy = False
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Health check for tenant %s failed: %s", tenant_app.codename, exc, exc_info=True)
                tenant_health[tenant_app.codename] = {
                    "status": "unhealthy",
                    "name": tenant_app.docs_name,
                    "error": str(exc),
                }
                all_healthy = False

        overall_status = "healthy" if all_healthy else "degraded"

        return JSONResponse(
            {
                "status": overall_status,
                "tenant_count": len(tenant_apps),
                "tenants": tenant_health,
                "infrastructure": {
                    "operation_mode": infra.operation_mode,
                },
                "boot_audit": boot_audit_state,
            },
            status_code=200,  # Always 200, check "status" field for degraded state
        )

    routes.insert(0, Route("/health", endpoint=health_check, methods=["GET"]))

    # Add root endpoint returning mcp.json format
    def root_mcp_config(request: Request) -> JSONResponse:
        """Root endpoint returning mcp.json configuration.

        This returns a ready-to-use configuration that can be copied
        directly into VS Code's mcp.json settings file.
        """
        # Generate mcp.json format from deployment config
        mcp_config = deployment_config.to_mcp_json()

        return JSONResponse(mcp_config)

    routes.insert(0, Route("/mcp.json", endpoint=root_mcp_config, methods=["GET"]))

    async def trigger_sync_endpoint(request: Request) -> JSONResponse:
        """Trigger a sync cycle for a tenant.

        Only available when running in online mode. Used for debugging
        the crawler without waiting for the scheduled sync.
        """
        if operation_mode != "online":
            return JSONResponse(
                {"success": False, "message": "Sync trigger only available in online mode"},
                status_code=503,
            )

        tenant_codename = request.path_params.get("tenant")
        if not tenant_codename:
            return JSONResponse(
                {"success": False, "message": "Missing tenant codename"},
                status_code=400,
            )

        tenant_app = tenant_registry.get_tenant(tenant_codename)
        if not tenant_app:
            return JSONResponse(
                {"success": False, "message": f"Tenant '{tenant_codename}' not found"},
                status_code=404,
            )

        # Get scheduler service from tenant
        scheduler_service = tenant_app.services.get_scheduler_service()

        # Initialize scheduler if not already running
        if not scheduler_service.is_initialized:
            logger.info("Initializing scheduler for tenant %s on first sync trigger", tenant_codename)
            init_result = await scheduler_service.initialize()
            if not init_result:
                return JSONResponse(
                    {"success": False, "message": "Failed to initialize scheduler for this tenant"},
                    status_code=503,
                )

        # Parse query parameters for force options
        force_crawler = request.query_params.get("force_crawler", "false").lower() == "true"
        force_full_sync = request.query_params.get("force_full_sync", "false").lower() == "true"

        result = await scheduler_service.trigger_sync(
            force_crawler=force_crawler,
            force_full_sync=force_full_sync,
        )

        status_code = 200 if result.get("success") else 500
        return JSONResponse(result, status_code=status_code)

    def sync_status_endpoint(request: Request) -> JSONResponse:
        """Get sync status for a tenant."""
        tenant_codename = request.path_params.get("tenant")
        if not tenant_codename:
            return JSONResponse(
                {"success": False, "message": "Missing tenant codename"},
                status_code=400,
            )

        tenant_app = tenant_registry.get_tenant(tenant_codename)
        if not tenant_app:
            return JSONResponse(
                {"success": False, "message": f"Tenant '{tenant_codename}' not found"},
                status_code=404,
            )

        scheduler_service = tenant_app.services.get_scheduler_service()
        scheduler = scheduler_service.scheduler

        if scheduler is None:
            return JSONResponse(
                {
                    "tenant": tenant_codename,
                    "scheduler_running": False,
                    "message": "Scheduler not initialized",
                }
            )

        return JSONResponse(
            {
                "tenant": tenant_codename,
                "scheduler_running": scheduler.running,
                "stats": scheduler.stats,
                "sitemap_urls": scheduler.sitemap_urls,
                "entry_urls": scheduler.entry_urls,
                "mode": scheduler.mode,
            }
        )

    routes.insert(0, Route("/{tenant}/sync/trigger", endpoint=trigger_sync_endpoint, methods=["POST"]))
    routes.insert(0, Route("/{tenant}/sync/status", endpoint=sync_status_endpoint, methods=["GET"]))

    # Create main Starlette app with combined lifespan
    app = Starlette(
        debug=infra.log_level.lower() == "debug",
        routes=routes,
        lifespan=combined_lifespan,
    )

    _register_signal_handlers(app)

    logger.info("Multi-tenant server initialized with %d tenants", len(tenant_apps))
    return app


def main() -> None:
    """Main entry point for multi-tenant server."""
    import uvicorn

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

    logger.info("=" * 80)
    logger.info("Starting Docs MCP Server")
    logger.info("Configuration: %s", config_path)
    logger.info("Tenants: %d", len(deployment_config.tenants))
    logger.info("=" * 80)

    # Create app
    app = create_app(config_path)

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
    )


if __name__ == "__main__":
    main()
