"""Tenant runtime primitives shared by the server and worker processes.

Production-optimized implementation with SIMD vectorization, lock-free concurrent
access, Bloom filter negative query optimization, and comprehensive performance
metrics collection.

This module provides a lightweight `TenantApp` that exposes only the core
behaviors (search, fetch, browse, health) through the production-optimized
`ProductionTenant` implementation. No fallback to legacy architecture.

Key properties:
- Zero FastMCP instances per tenant (only one global server)
- No background tasks in the HTTP lifecycle; workers own schedulers
- Direct delegation to production tenant for all operations
- Production optimizations: SIMD, lock-free, Bloom filters, metrics
"""

from __future__ import annotations

from .deployment_config import TenantConfig
from .production_tenant import ProductionTenant
from .utils.models import BrowseTreeResponse, FetchDocResponse, SearchDocsResponse


class TenantApp:
    """Simplified tenant app that delegates to production tenant."""

    def __init__(self, tenant_config: TenantConfig):
        self.tenant_config = tenant_config
        self.codename = tenant_config.codename
        self.docs_name = tenant_config.docs_name
        self._production_tenant = ProductionTenant(tenant_config)

    async def initialize(self) -> None:
        """No-op initialization for production tenant."""

    async def shutdown(self) -> None:
        """Shutdown production tenant."""
        if self._production_tenant:
            self._production_tenant.close()

    async def search(self, query: str, size: int, word_match: bool) -> SearchDocsResponse:
        """Delegate to production tenant."""
        return self._production_tenant.search(query, size, word_match)

    async def fetch(self, uri: str, context: str | None) -> FetchDocResponse:
        """Delegate to production tenant."""
        return self._production_tenant.fetch(uri, context)

    async def browse_tree(self, path: str, depth: int) -> BrowseTreeResponse:
        """Delegate to production tenant."""
        return self._production_tenant.browse_tree(path, depth)

    def get_performance_stats(self) -> dict:
        """Delegate to production tenant."""
        return self._production_tenant.get_performance_stats()


def create_tenant_app(
    tenant_config: TenantConfig,
) -> TenantApp:
    return TenantApp(tenant_config)
