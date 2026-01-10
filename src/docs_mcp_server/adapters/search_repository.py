"""Search repository abstractions and implementations.

Defines the search infrastructure layer following Repository Pattern.
Separates search concerns from business logic.
"""

from abc import ABC, abstractmethod
import logging
from pathlib import Path

from docs_mcp_server.domain.search import (
    SearchQuery,
    SearchResponse,
)


logger = logging.getLogger(__name__)


class AbstractSearchRepository(ABC):
    """Abstract repository for searching documents.

    Implementations can use different search engines (BM25, full-text search, etc.).
    """

    @abstractmethod
    async def search_documents(
        self,
        query: SearchQuery,
        data_dir: Path,
        max_results: int = 20,
        word_match: bool = False,
        include_stats: bool = False,
        include_debug: bool = False,
    ) -> SearchResponse:
        """Search documents in the given data directory.

        Args:
            query: Analyzed search query with keywords and tokens
            data_dir: Root directory containing markdown documents
            max_results: Maximum number of results to return
            word_match: Enable whole word matching
            include_stats: Whether to include search performance statistics
            include_debug: Whether callers requested verbose match trace metadata

        Returns:
            SearchResponse containing results and optional stats
        """
        raise NotImplementedError

    async def warm_cache(self, data_dir: Path) -> None:
        """Optional hook for warming repository caches for a data directory."""

        return

    def invalidate_cache(self, data_dir: Path | None = None) -> None:
        """Optional hook for invalidating cached state for a directory or all directories."""

        return

    async def reload_cache(self, data_dir: Path) -> bool:
        """Optional hook for forcing a synchronous cache reload from disk."""

        return False

    def get_cache_metrics(self, data_dir: Path | None = None) -> dict[str, dict[str, float | int]]:
        """Optional hook returning cache instrumentation data."""

        return {}
