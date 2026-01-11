"""Zero-dependency tenant - Phase 4: Dependency Injection Elimination.

Eliminates all dependency injection patterns:
- No TenantServices container
- No service interfaces - concrete classes only
- Inline configuration - primitive parameters only
- No factory patterns - direct instantiation
- RAII lifecycle management
- Zero dependency injection framework

Target: Zero dependency injection overhead
"""

import logging
from pathlib import Path

from docs_mcp_server.search.latency_optimized_index import LatencyOptimizedSearchIndex
from docs_mcp_server.utils.models import SearchDocsResponse, SearchResult


logger = logging.getLogger(__name__)


class ZeroDependencyTenant:
    """Phase 4: Zero dependency injection tenant.

    Eliminates all DI patterns:
    - Direct construction only
    - Concrete classes, no interfaces
    - Primitive configuration parameters
    - RAII resource management
    - No service containers or factories
    """

    def __init__(self, codename: str, data_path: str):
        """Direct construction with primitive parameters."""
        self.codename = codename
        self._data_path = Path(data_path)

        # Direct instantiation - no DI container
        search_db_path = self._data_path / "__search_segments" / "search.db"
        self._search_index = LatencyOptimizedSearchIndex(search_db_path) if search_db_path.exists() else None

    def search(self, query: str, size: int, word_match: bool) -> SearchDocsResponse:
        """Direct search execution without service layers."""
        if not self._search_index:
            return SearchDocsResponse(results=[], error=f"No search index for {self.codename}", query=query)

        try:
            # Direct call - no service orchestration
            search_response = self._search_index.search(query, size)

            # Direct result conversion
            results = [
                SearchResult(title=result.title, url=result.url, snippet=result.snippet, score=result.score)
                for result in search_response.results
            ]

            return SearchDocsResponse(results=results)

        except Exception as e:
            logger.error(f"Search failed for {self.codename}: {e}")
            return SearchDocsResponse(results=[], error=str(e), query=query)

    def close(self):
        """RAII cleanup - no lifecycle management complexity."""
        if self._search_index:
            self._search_index.close()
            self._search_index = None
