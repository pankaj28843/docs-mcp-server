"""Composable builder for the multi-tenant FastMCP server."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route

from docs_mcp_server.observability import (
    build_trace_resource_attributes,
    configure_log_exporter,
    configure_logging,
    configure_metrics_exporter,
    configure_trace_exporter,
    get_metrics,
    get_metrics_content_type,
    init_log_exporter,
    init_metrics,
    init_tracing,
)
from docs_mcp_server.observability.tracing import TraceContextMiddleware, trace_request
from docs_mcp_server.runtime.health import build_health_endpoint
from docs_mcp_server.runtime.signals import install_shutdown_signals
from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore

from .config import Settings
from .deployment_config import DeploymentConfig
from .registry import TenantRegistry
from .root_hub import create_root_hub
from .tenant import create_tenant_app
from .ui.dashboard import render_dashboard_html, render_tenant_dashboard_html


if TYPE_CHECKING:
    from starlette.requests import Request


logger = logging.getLogger(__name__)
_SHUTDOWN_DRAIN_TIMEOUT_S = 30.0


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

    def build(self) -> Starlette | None:
        """Build and return the Starlette application."""

        config_payload = self._load_config()
        if config_payload is None:
            return None
        self.deployment_config, self.env_driven_config = config_payload

        infra = self.deployment_config.infrastructure

        # Initialize observability using the active log profile
        profile = infra.get_active_log_profile()
        configure_logging(
            level=profile.level,
            json_output=profile.json_output,
            logger_levels=profile.logger_levels,
            trace_categories=profile.trace_categories,
            trace_level=profile.trace_level,
            access_log=profile.access_log,
        )
        collector_config = infra.observability_collector
        resource_attributes = build_trace_resource_attributes(collector_config)
        configure_metrics_exporter(
            collector_config,
            service_name="docs-mcp-server",
            resource_attributes=resource_attributes,
        )
        init_metrics(service_name="docs-mcp-server", resource_attributes=resource_attributes)
        init_tracing(service_name="docs-mcp-server", resource_attributes=resource_attributes)
        configure_trace_exporter(collector_config)
        init_log_exporter(service_name="docs-mcp-server", resource_attributes=resource_attributes)
        configure_log_exporter(collector_config)

        SqliteSegmentStore.set_max_segments(infra.search_max_segments)

        self._initialize_tenants()
        routes = self._build_routes(infra)
        lifespan = self._build_lifespan_manager()

        app = Starlette(
            debug=infra.log_level.lower() == "debug",
            routes=routes,
            lifespan=lifespan,
        )
        if infra.trusted_hosts:
            app.add_middleware(TrustedHostMiddleware, allowed_hosts=infra.trusted_hosts)
        if infra.https_redirect:
            app.add_middleware(HTTPSRedirectMiddleware)
        app.middleware("http")(trace_request)
        app.add_middleware(TraceContextMiddleware)

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
        routes: list[Route | Mount] = [Mount("/mcp", app=self.root_hub_http_app)]
        routes.append(Route("/health", endpoint=build_health_endpoint(self.tenant_apps, infra), methods=["GET"]))
        routes.append(Route("/metrics", endpoint=self._build_metrics_endpoint(), methods=["GET"]))
        routes.append(Route("/mcp.json", endpoint=self._build_mcp_config_endpoint(), methods=["GET"]))
        routes.append(
            Route(
                "/dashboard",
                endpoint=self._build_dashboard_endpoint(operation_mode=infra.operation_mode),
                methods=["GET"],
            )
        )
        routes.append(
            Route(
                "/dashboard/{tenant}",
                endpoint=self._build_dashboard_tenant_endpoint(operation_mode=infra.operation_mode),
                methods=["GET"],
            )
        )
        routes.append(
            Route(
                "/dashboard/{tenant}/events",
                endpoint=self._build_dashboard_events_endpoint(operation_mode=infra.operation_mode),
                methods=["GET"],
            )
        )
        routes.append(
            Route(
                "/dashboard/{tenant}/events/logs",
                endpoint=self._build_dashboard_event_logs_endpoint(operation_mode=infra.operation_mode),
                methods=["GET"],
            )
        )
        routes.append(Route("/tenants/status", endpoint=self._build_tenants_status_endpoint(), methods=["GET"]))
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

    def _build_metrics_endpoint(self):
        async def metrics_endpoint(_: Request) -> Response:
            return Response(content=get_metrics(), media_type=get_metrics_content_type())

        return metrics_endpoint

    def _build_dashboard_endpoint(self, operation_mode: Literal["online", "offline"]):
        async def dashboard_endpoint(_: Request) -> Response:
            if operation_mode != "online":
                return HTMLResponse(
                    "<!doctype html><html><body><h1>Dashboard unavailable</h1>"
                    "<p>Dashboard is only available in online mode.</p></body></html>",
                    status_code=503,
                )

            codenames = self._list_dashboard_tenants()
            return HTMLResponse(render_dashboard_html(codenames))

        return dashboard_endpoint

    def _build_dashboard_tenant_endpoint(self, operation_mode: Literal["online", "offline"]):
        async def dashboard_tenant_endpoint(request: Request) -> Response:
            if operation_mode != "online":
                return HTMLResponse(
                    "<!doctype html><html><body><h1>Dashboard unavailable</h1>"
                    "<p>Dashboard is only available in online mode.</p></body></html>",
                    status_code=503,
                )

            tenant_codename = request.path_params.get("tenant")
            if not tenant_codename:
                return HTMLResponse(
                    "<!doctype html><html><body>Missing tenant codename.</body></html>", status_code=400
                )
            if not self._is_dashboard_tenant(tenant_codename):
                return HTMLResponse(
                    "<!doctype html><html><body>Tenant not found.</body></html>",
                    status_code=404,
                )
            return HTMLResponse(render_tenant_dashboard_html(tenant_codename))

        return dashboard_tenant_endpoint

    def _build_dashboard_events_endpoint(self, operation_mode: Literal["online", "offline"]):
        async def dashboard_events_endpoint(request: Request) -> JSONResponse:
            tenant_codename = request.path_params.get("tenant")
            metadata_store = None
            error: JSONResponse | None = None
            if operation_mode != "online":
                error = JSONResponse(
                    {"success": False, "message": "Dashboard is only available in online mode"},
                    status_code=503,
                )
            elif not tenant_codename:
                error = JSONResponse({"success": False, "message": "Missing tenant codename"}, status_code=400)
            elif not self._is_dashboard_tenant(tenant_codename):
                error = JSONResponse({"success": False, "message": "Tenant not found"}, status_code=404)
            else:
                tenant_app = self.tenant_registry.get_tenant(tenant_codename)
                if tenant_app is None:
                    error = JSONResponse({"success": False, "message": "Tenant not found"}, status_code=404)
                else:
                    scheduler_service = tenant_app.sync_runtime.get_scheduler_service()
                    metadata_store = getattr(scheduler_service, "metadata_store", None)
                    if metadata_store is None:
                        error = JSONResponse({"success": False, "message": "History unavailable"}, status_code=503)
            if error:
                return error

            def parse_int_param(
                name: str,
                *,
                default: int | None,
                min_value: int,
                max_value: int,
            ) -> tuple[int | None, JSONResponse | None]:
                raw_value = request.query_params.get(name)
                if raw_value is None or raw_value == "":
                    return default, None
                try:
                    parsed = int(raw_value)
                except ValueError:
                    return None, JSONResponse({"success": False, "message": f"Invalid {name}"}, status_code=400)
                if parsed < min_value or parsed > max_value:
                    return None, JSONResponse({"success": False, "message": f"Invalid {name}"}, status_code=400)
                return parsed, None

            range_days, error = parse_int_param("range_days", default=None, min_value=1, max_value=365)
            if error:
                return error
            bucket_minutes, error = parse_int_param("bucket_minutes", default=None, min_value=1, max_value=1440)
            if error:
                return error
            limit, error = parse_int_param("limit", default=5000, min_value=1, max_value=20000)
            if error:
                return error
            if metadata_store is None:
                return JSONResponse({"success": False, "message": "History unavailable"}, status_code=503)
            history = await metadata_store.get_event_history(
                range_days=range_days,
                minutes=60,
                bucket_seconds=bucket_minutes * 60 if bucket_minutes else 60,
                limit=limit,
            )
            return JSONResponse(history)

        return dashboard_events_endpoint

    def _build_dashboard_event_logs_endpoint(self, operation_mode: Literal["online", "offline"]):
        async def dashboard_event_logs_endpoint(request: Request) -> JSONResponse:
            if operation_mode != "online":
                return JSONResponse(
                    {"success": False, "message": "Dashboard is only available in online mode"},
                    status_code=503,
                )

            tenant_codename = request.path_params.get("tenant")
            if not tenant_codename:
                return JSONResponse({"success": False, "message": "Missing tenant codename"}, status_code=400)
            if not self._is_dashboard_tenant(tenant_codename):
                return JSONResponse({"success": False, "message": "Tenant not found"}, status_code=404)

            tenant_app = self.tenant_registry.get_tenant(tenant_codename)
            if tenant_app is None:
                return JSONResponse({"success": False, "message": "Tenant not found"}, status_code=404)

            scheduler_service = tenant_app.sync_runtime.get_scheduler_service()
            metadata_store = getattr(scheduler_service, "metadata_store", None)
            if metadata_store is None:
                return JSONResponse({"success": False, "message": "History unavailable"}, status_code=503)

            event_type = request.query_params.get("event_type") or None
            status = request.query_params.get("status") or None
            limit_raw = request.query_params.get("limit")
            limit = 200
            if limit_raw:
                try:
                    limit = int(limit_raw)
                except ValueError:
                    return JSONResponse({"success": False, "message": "Invalid limit"}, status_code=400)
                if limit < 1 or limit > 1000:
                    return JSONResponse({"success": False, "message": "Invalid limit"}, status_code=400)
            payload = await metadata_store.get_event_log(
                event_type=event_type,
                status=status,
                limit=limit,
            )
            return JSONResponse(payload)

        return dashboard_event_logs_endpoint

    def _list_dashboard_tenants(self) -> list[str]:
        return [codename for codename in self.tenant_registry.list_codenames() if self._is_dashboard_tenant(codename)]

    def _is_dashboard_tenant(self, codename: str) -> bool:
        config = self.tenant_configs_map.get(codename)
        source_type = getattr(config, "source_type", None)
        if source_type not in {"online", "git"}:
            return False

        tenant_app = self.tenant_registry.get_tenant(codename)
        if tenant_app is None:
            return False
        sync_runtime = getattr(tenant_app, "sync_runtime", None)
        if sync_runtime is None or not hasattr(sync_runtime, "get_scheduler_service"):
            return False
        scheduler_service = sync_runtime.get_scheduler_service()
        metadata_store = getattr(scheduler_service, "metadata_store", None)
        return metadata_store is not None

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

    def _build_tenants_status_endpoint(self):
        async def tenants_status_endpoint(_: Request) -> JSONResponse:
            codenames = self.tenant_registry.list_codenames()

            async def build_status(codename: str) -> dict[str, Any]:
                tenant_app = self.tenant_registry.get_tenant(codename)
                if tenant_app is None:
                    return {"tenant": codename, "error": "missing"}
                try:
                    scheduler_service = tenant_app.sync_runtime.get_scheduler_service()
                    crawl_snapshot = await scheduler_service.get_status_snapshot()
                    index_status = tenant_app.get_index_status()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("Failed to build status for tenant %s", codename)
                    return {
                        "tenant": codename,
                        "error": "status_failed",
                        "detail": str(exc),
                    }
                else:
                    return {
                        "tenant": codename,
                        "crawl": crawl_snapshot,
                        "index": index_status,
                    }

            results = await asyncio.gather(*(build_status(codename) for codename in codenames))

            def _parse_timestamp(value: str | None) -> datetime | None:
                if not value:
                    return None
                try:
                    parsed = datetime.fromisoformat(value)
                except (TypeError, ValueError):
                    return None
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed

            def sort_key(item: dict[str, Any]) -> tuple[int, datetime]:
                crawl_stats = item.get("crawl", {}).get("stats", {})
                last_event = (
                    crawl_stats.get("last_sync_at")
                    or crawl_stats.get("metadata_last_success_at")
                    or crawl_stats.get("metadata_first_seen_at")
                )
                parsed = _parse_timestamp(last_event) or datetime.min.replace(tzinfo=timezone.utc)
                return (0 if last_event else 1, parsed)

            results.sort(key=sort_key, reverse=True)
            return JSONResponse({"tenants": results, "count": len(results)})

        return tenants_status_endpoint

    def _build_lifespan_manager(self):
        assert self.root_hub_http_app is not None

        @asynccontextmanager
        async def combined_lifespan(app: Starlette):
            await asyncio.gather(*(tenant.initialize() for tenant in self.tenant_apps))

            contexts = []
            ctx = self.root_hub_http_app.lifespan(app)
            contexts.append(ctx)
            await ctx.__aenter__()

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
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(drain("signal")),
                            timeout=_SHUTDOWN_DRAIN_TIMEOUT_S,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("Tenant drain timed out after %ss (signal)", _SHUTDOWN_DRAIN_TIMEOUT_S)

                shutdown_monitor = asyncio.create_task(watch_shutdown())

            try:
                yield
            finally:
                if shutdown_monitor is not None:
                    shutdown_monitor.cancel()
                    with suppress(asyncio.CancelledError):
                        await shutdown_monitor
                try:
                    await asyncio.wait_for(
                        asyncio.shield(drain("lifespan-exit")),
                        timeout=_SHUTDOWN_DRAIN_TIMEOUT_S,
                    )
                except asyncio.TimeoutError:
                    logger.warning("Tenant drain timed out after %ss (lifespan)", _SHUTDOWN_DRAIN_TIMEOUT_S)
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
