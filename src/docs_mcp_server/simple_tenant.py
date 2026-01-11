"""Simplified tenant implementation using deep modules.

Eliminates TenantServices dependency injection container and complex service layers.
Uses direct construction and simple interfaces per "Philosophy of Software Design".
"""

import logging
from pathlib import Path

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.search.search_index import SearchIndex
from docs_mcp_server.utils.models import SearchDocsResponse, SearchResult


logger = logging.getLogger(__name__)


class SimpleTenantApp:
    """Simplified tenant app with direct construction.

    Eliminates dependency injection complexity and service layers.
    Uses deep modules with simple interfaces.
    """

    def __init__(self, tenant_config: TenantConfig):
        """Initialize tenant with direct construction."""
        self.tenant_config = tenant_config
        self.codename = tenant_config.codename

        # Direct construction - no DI container
        search_db_path = self._get_search_db_path()
        self._search_index = SearchIndex(search_db_path) if search_db_path.exists() else None

    def _get_search_db_path(self) -> Path:
        """Get path to search database."""
        # Use same path logic as current implementation
        data_dir = Path(f"data/{self.codename}")
        return data_dir / "__search_segments" / "search.db"

    async def search(self, query: str, size: int, word_match: bool) -> SearchDocsResponse:
        """Search documents using simplified index.

        Args:
            query: Natural language search query
            size: Maximum results to return
            word_match: Ignored in simplified implementation

        Returns:
            SearchDocsResponse with results
        """
        if not self._search_index:
            logger.warning(f"No search index found for tenant {self.codename}")
            return SearchDocsResponse(results=[], error=f"No search index for {self.codename}", query=query)

        try:
            search_response = self._search_index.search(query, size)

            # Convert to expected format
            results = []
            for result in search_response.results:
                search_result = SearchResult(
                    title=result.title, url=result.url, snippet=result.snippet, score=result.score
                )
                results.append(search_result)

            return SearchDocsResponse(results=results)

        except Exception as e:
            logger.error(f"Search failed for tenant {self.codename}: {e}")
            return SearchDocsResponse(results=[], error=str(e), query=query)

    async def list_documents(self, path: str = "") -> list[dict]:
        """List available documents - simplified implementation."""
        # For now, return empty list - can be enhanced later
        return []

    async def fetch_document(self, uri: str, context: str | None = None) -> dict:
        """Fetch document content - simplified implementation."""
        # For now, return empty dict - can be enhanced later
        return {"title": "", "content": ""}

    async def shutdown(self):
        """Clean shutdown."""
        if self._search_index:
            self._search_index.close()
            self._search_index = None
