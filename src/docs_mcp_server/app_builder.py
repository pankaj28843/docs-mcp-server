"""Composable builder for the multi-tenant FastMCP server."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import logging
from pathlib import Path
import re
from typing import TYPE_CHECKING, Literal

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from docs_mcp_server.runtime.health import build_health_endpoint
from docs_mcp_server.runtime.signals import install_shutdown_signals
from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore

from .config import Settings
from .deployment_config import DeploymentConfig
from .registry import TenantRegistry
from .root_hub import create_root_hub
from .service_layer.boot_audit_service import BootAuditService
from .tenant import create_tenant_app


if TYPE_CHECKING:
    from starlette.requests import Request


logger = logging.getLogger(__name__)


class AppBuilder:
    """Builds the ASGI app from deployment config or environment variables."""

    def __init__(self, config_path: Path | str | None = None) -> None:
        self.config_path = Path(config_path) if config_path else Path("deployment.json")
        self.env_driven_config = False
        self.deployment_config: DeploymentConfig | None = None
        self.tenant_apps = []
        self.tenant_configs_map: dict[str, object] = {}
        self.tenant_registry = TenantRegistry()
        self.root_hub_http_app = None
        self.boot_audit_service: BootAuditService | None = None

    def build(self) -> Starlette | None:
        """Build and return the Starlette application."""

        config_payload = self._load_config()
        if config_payload is None:
            return None
        self.deployment_config, self.env_driven_config = config_payload

        infra = self.deployment_config.infrastructure

        SqliteSegmentStore.set_max_segments(infra.search_max_segments)

        self._initialize_tenants()
        routes = self._build_routes(infra)
        lifespan = self._build_lifespan_manager()

        app = Starlette(
            debug=infra.log_level.lower() == "debug",
            routes=routes,
            lifespan=lifespan,
        )

        install_shutdown_signals(app)
        logger.info("Multi-tenant server initialized with %d tenants", len(self.tenant_apps))
        return app

    def _load_config(self) -> tuple[DeploymentConfig, bool] | None:
        if Path(self.config_path).exists():
            logger.info("Loading deployment configuration from %s", self.config_path)
            try:
                config = DeploymentConfig.from_json_file(Path(self.config_path))
            except ValidationError as exc:
                logger.error("Deployment configuration is invalid: %s", exc)
                return None
            return config, False

        logger.info(
            "Deployment config %s not found, attempting environment-driven single-tenant mode",
            self.config_path,
        )
        try:
            config = _build_env_deployment_from_env()
        except (ValidationError, ValueError) as exc:
            logger.error("Environment-driven deployment configuration failed: %s", exc)
            raise FileNotFoundError(
                f"Deployment config not found: {self.config_path}\n"
                "Please create deployment.json or supply DOCS_* env vars."
            ) from exc
        else:
            tenant_code = config.tenants[0].codename if config.tenants else "unknown"
            logger.info("Using env-driven deployment for tenant: %s", tenant_code)
            return config, True

    def _initialize_tenants(self) -> None:
        assert self.deployment_config is not None
        for tenant_config in self.deployment_config.tenants:
            logger.info("Initializing tenant: %s (%s)", tenant_config.codename, tenant_config.docs_name)
            tenant_app = create_tenant_app(tenant_config)
            self.tenant_apps.append(tenant_app)
            self.tenant_configs_map[tenant_app.codename] = tenant_config
            self.tenant_registry.register(tenant_config, tenant_app)

    def _build_routes(self, infra) -> list:
        root_hub = create_root_hub(self.tenant_registry)
        self.root_hub_http_app = root_hub.http_app(
            path="/",
            json_response=True,
            stateless_http=True,
        )
        self.boot_audit_service = BootAuditService(config_path=self.config_path, tenant_count=len(self.tenant_apps))

        routes: list[Route | Mount] = [Mount("/mcp", app=self.root_hub_http_app)]
        routes.append(Route("/health", endpoint=build_health_endpoint(self.tenant_apps, infra), methods=["GET"]))
        routes.append(Route("/mcp.json", endpoint=self._build_mcp_config_endpoint(), methods=["GET"]))
        routes.append(Route("/{tenant}/sync/status", endpoint=self._build_sync_status_endpoint(), methods=["GET"]))
        routes.append(
            Route(
                "/{tenant}/sync/trigger",
                endpoint=self._build_sync_trigger_endpoint(operation_mode=infra.operation_mode),
                methods=["POST"],
            )
        )
        return routes

    def _build_mcp_config_endpoint(self):
        assert self.deployment_config is not None

        async def root_mcp_config(_: Request) -> JSONResponse:
            return JSONResponse(self.deployment_config.to_mcp_json())

        return root_mcp_config

    def _build_sync_trigger_endpoint(self, operation_mode: Literal["online", "offline"]):
        async def trigger_sync_endpoint(request: Request) -> JSONResponse:
            if operation_mode != "online":
                return JSONResponse(
                    {"success": False, "message": "Sync trigger only available in online mode"},
                    status_code=503,
                )

            tenant_codename = request.path_params.get("tenant")
            if not tenant_codename:
                return JSONResponse({"success": False, "message": "Missing tenant codename"}, status_code=400)

            tenant_app = self.tenant_registry.get_tenant(tenant_codename)
            if not tenant_app:
                available = ", ".join(self.tenant_registry.list_codenames())
                return JSONResponse(
                    {"success": False, "message": f"Tenant '{tenant_codename}' not found. Available: {available}"},
                    status_code=404,
                )

            scheduler_service = tenant_app.sync_runtime.get_scheduler_service()

            if not scheduler_service.is_initialized:
                logger.info("Initializing scheduler for tenant %s on first sync trigger", tenant_codename)
                init_result = await scheduler_service.initialize()
                if not init_result:
                    return JSONResponse(
                        {"success": False, "message": "Failed to initialize scheduler for this tenant"},
                        status_code=503,
                    )

            force_crawler = request.query_params.get("force_crawler", "false").lower() == "true"
            force_full_sync = request.query_params.get("force_full_sync", "false").lower() == "true"

            result = await scheduler_service.trigger_sync(
                force_crawler=force_crawler,
                force_full_sync=force_full_sync,
            )

            status_code = 200 if result.get("success") else 500
            return JSONResponse(result, status_code=status_code)

        return trigger_sync_endpoint

    def _build_sync_status_endpoint(self):
        async def sync_status_endpoint(request: Request) -> JSONResponse:
            tenant_codename = request.path_params.get("tenant")
            if not tenant_codename:
                return JSONResponse({"success": False, "message": "Missing tenant codename"}, status_code=400)

            tenant_app = self.tenant_registry.get_tenant(tenant_codename)
            if not tenant_app:
                available = ", ".join(self.tenant_registry.list_codenames())
                return JSONResponse(
                    {"success": False, "message": f"Tenant '{tenant_codename}' not found. Available: {available}"},
                    status_code=404,
                )

            scheduler_service = tenant_app.sync_runtime.get_scheduler_service()
            snapshot = await scheduler_service.get_status_snapshot()
            return JSONResponse({"tenant": tenant_codename, **snapshot})

        return sync_status_endpoint

    def _build_lifespan_manager(self):
        assert self.boot_audit_service is not None
        assert self.root_hub_http_app is not None

        @asynccontextmanager
        async def combined_lifespan(app: Starlette):
            app.state.boot_audit_service = self.boot_audit_service

            await asyncio.gather(*(tenant.initialize() for tenant in self.tenant_apps))

            contexts = []
            ctx = self.root_hub_http_app.lifespan(app)
            contexts.append(ctx)
            await ctx.__aenter__()

            boot_audit_task: asyncio.Task | None = None
            if not self.env_driven_config:
                boot_audit_task = self.boot_audit_service.schedule()

            drained = False

            async def drain(reason: str) -> None:
                nonlocal drained
                if drained:
                    return
                drained = True
                logger.info("Draining tenant residency (%s)", reason)
                await asyncio.gather(*(tenant.shutdown() for tenant in self.tenant_apps), return_exceptions=True)

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
                    self.boot_audit_service.cancel()
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
                    except Exception as exc:  # pragma: no cover - best effort cleanup
                        logger.error("Error during lifespan cleanup: %s", exc, exc_info=True)

        return combined_lifespan


def _derive_env_tenant_codename(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        slug = "docs"
    if not slug[0].isalpha():
        slug = f"docs-{slug}"
    if len(slug) < 2:
        slug = slug.ljust(2, "x")
    return slug[:64]


def _build_env_deployment_from_env() -> DeploymentConfig:
    settings = Settings()
    docs_name = settings.docs_name.strip()
    if not docs_name:
        raise ValueError("DOCS_NAME must be set for env-driven single tenant mode.")

    if not settings.get_docs_entry_urls() and not settings.get_docs_sitemap_urls():
        raise ValueError("DOCS_ENTRY_URL or DOCS_SITEMAP_URL must be provided when running without deployment.json.")

    tenant_payload = {
        "codename": _derive_env_tenant_codename(docs_name),
        "docs_name": docs_name,
        "docs_entry_url": settings.get_docs_entry_urls(),
        "docs_sitemap_url": settings.get_docs_sitemap_urls(),
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

    fallback_payload = {
        "enabled": settings.fallback_extractor_enabled,
        "endpoint": settings.fallback_extractor_endpoint or None,
        "timeout_seconds": settings.fallback_extractor_timeout_seconds,
        "batch_size": settings.fallback_extractor_batch_size,
        "max_retries": settings.fallback_extractor_max_retries,
        "api_key_env": settings.fallback_extractor_api_key_env or None,
    }
    infra_payload["article_extractor_fallback"] = fallback_payload

    return DeploymentConfig(
        infrastructure=infra_payload,
        tenants=[tenant_payload],
    )
