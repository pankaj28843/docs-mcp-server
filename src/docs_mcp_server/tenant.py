"""Tenant runtime primitives shared by the server and worker processes.

Deep module implementation using DocumentationSearchEngine for all operations.
Eliminates interface proliferation while maintaining performance optimizations
through internal optimization routing.

Key properties:
- Single DocumentationSearchEngine handles all search functionality
- Automatic optimization selection (SIMD → lock-free → Bloom → basic)
- Sub-200ms search latency maintained through internal routing
- Simple interface hiding optimization complexity
"""

from __future__ import annotations

from typing import Any

from .deployment_config import TenantConfig
from .documentation_search_engine import DocumentationSearchEngine
from .utils.models import BrowseTreeResponse, FetchDocResponse, SearchDocsResponse


class MockSchedulerService:
    """Mock scheduler service for simplified tenant implementation."""

    def __init__(self, tenant_codename: str):
        self.tenant_codename = tenant_codename

    async def get_status_snapshot(self) -> dict[str, Any]:
        """Return minimal status snapshot."""
        return {
            "scheduler_running": False,
            "scheduler_initialized": False,
            "stats": {
                "mode": "offline",
                "refresh_schedule": None,
                "scheduler_running": False,
                "scheduler_initialized": False,
                "storage_doc_count": 0,
                "queue_depth": 0,
                "metadata_total_urls": 0,
                "metadata_due_urls": 0,
                "metadata_successful": 0,
                "metadata_pending": 0,
                "metadata_first_seen_at": None,
                "metadata_last_success_at": None,
                "metadata_sample": [],
                "failed_url_count": 0,
                "failure_sample": [],
                "fallback_attempts": 0,
                "fallback_successes": 0,
                "fallback_failures": 0,
            },
        }


class MockSyncRuntime:
    """Mock sync runtime for simplified tenant implementation."""

    def __init__(self, tenant_codename: str):
        self._scheduler_service = MockSchedulerService(tenant_codename)

    def get_scheduler_service(self) -> MockSchedulerService:
        """Return mock scheduler service."""
        return self._scheduler_service


class TenantApp:
    """Simplified tenant app that delegates to DocumentationSearchEngine."""

    def __init__(self, tenant_config: TenantConfig):
        self.tenant_config = tenant_config
        self.codename = tenant_config.codename
        self.docs_name = tenant_config.docs_name
        self._documentation_search_engine = DocumentationSearchEngine(tenant_config)
        self.sync_runtime = MockSyncRuntime(tenant_config.codename)

    async def initialize(self) -> None:
        """No-op initialization for documentation search engine."""

    async def shutdown(self) -> None:
        """Shutdown documentation search engine."""
        if self._documentation_search_engine:
            self._documentation_search_engine.close()

    async def search(self, query: str, size: int, word_match: bool) -> SearchDocsResponse:
        """Search documents using documentation search engine."""
        return self._documentation_search_engine.search_documents(query, size, word_match)

    async def fetch(self, uri: str, context: str | None) -> FetchDocResponse:
        """Fetch document content using documentation search engine."""
        return self._documentation_search_engine.fetch_document_content(uri, context)

    async def browse_tree(self, path: str, depth: int) -> BrowseTreeResponse:
        """Browse document tree using documentation search engine."""
        return self._documentation_search_engine.browse_document_tree(path, depth)

    def get_performance_stats(self) -> dict:
        """Get performance statistics from documentation search engine."""
        return self._documentation_search_engine.get_performance_metrics()

    def supports_browse(self) -> bool:
        """Determine if this tenant supports browsing the document tree."""
        return self.tenant_config.supports_browse

    async def health(self) -> dict:
        """Return health status."""
        return {"status": "healthy", "tenant": self.codename}


def create_tenant_app(tenant_config: TenantConfig) -> TenantApp:
    """Create tenant app with DocumentationSearchEngine."""
    return TenantApp(tenant_config)
