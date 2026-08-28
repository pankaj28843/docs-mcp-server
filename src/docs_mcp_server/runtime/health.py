"""Health endpoint factory."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from starlette.responses import JSONResponse


if TYPE_CHECKING:
    from starlette.requests import Request


class _SnapshotRuntime(Protocol):
    def snapshot(self) -> dict: ...


def build_health_endpoint(
    tenant_apps: Sequence,
    infra: object,
    browser_runtime: _SnapshotRuntime | None = None,
):
    """Return a coroutine function that aggregates tenant health data."""

    async def health_check(request: Request) -> JSONResponse:
        tenant_health: dict[str, dict] = {}
        all_healthy = True

        for tenant_app in tenant_apps:
            try:
                tenant_health[tenant_app.codename] = await tenant_app.health()
                if tenant_health[tenant_app.codename]["status"] != "healthy":
                    all_healthy = False
            except Exception as exc:  # pragma: no cover - defensive guard rails
                tenant_health[tenant_app.codename] = {
                    "status": "unhealthy",
                    "name": tenant_app.docs_name,
                    "error": str(exc),
                }
                all_healthy = False

        browser = browser_runtime.snapshot() if browser_runtime else None
        if browser is not None and not browser["ready"]:
            all_healthy = False
        overall_status = "healthy" if all_healthy else "degraded"

        return JSONResponse(
            {
                "status": overall_status,
                "tenant_count": len(tenant_apps),
                "tenants": tenant_health,
                "infrastructure": {
                    "operation_mode": getattr(infra, "operation_mode", "online"),
                    "browser": browser,
                },
            }
        )

    return health_check


def build_liveness_endpoint():
    """Return a constant-time process liveness endpoint.

    ``/health`` intentionally performs a detailed tenant aggregate and can be
    slow while a large deployment is crawling.  Liveness probes must only
    answer whether the ASGI process can serve requests, so they must not touch
    tenant state or the filesystem.
    """

    async def liveness_check(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return liveness_check
