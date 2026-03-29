"""Health endpoint factory."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse


if TYPE_CHECKING:
    from starlette.requests import Request


def build_health_endpoint(tenant_apps: Sequence, infra: object):
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

        overall_status = "healthy" if all_healthy else "degraded"

        return JSONResponse(
            {
                "status": overall_status,
                "tenant_count": len(tenant_apps),
                "tenants": tenant_health,
                "infrastructure": {
                    "operation_mode": getattr(infra, "operation_mode", "online"),
                },
            }
        )

    return health_check
