"""Search service orchestration layer.

Combines query analysis and search execution for clean interface.
Provides high-level search API for tenant layer.
"""

import logging
from pathlib import Path

from docs_mcp_server.adapters.search_repository import AbstractSearchRepository
from docs_mcp_server.domain.search import SearchResponse
from docs_mcp_server.services.keyword_service import (
    KeywordExtractionService,
    QueryAnalysisService,
)


logger = logging.getLogger(__name__)


class SearchService:
    """High-level search orchestration service.

    Coordinates query analysis and document search using BM25-indexed search.
    Provides clean API for MCP tools.
    """

    def __init__(
        self,
        search_repository: AbstractSearchRepository,
    ):
        """Initialize search service with dependencies.

        Args:
            search_repository: BM25 index repository implementation (required)
        """
        self.keyword_extractor = KeywordExtractionService()
        self.query_analyzer = QueryAnalysisService(self.keyword_extractor)
        self.search_repository = search_repository

    async def search(
        self,
        raw_query: str,
        data_dir: Path,
        max_results: int = 20,
        word_match: bool = False,
        include_stats: bool = False,
        tenant_context: str | None = None,
        include_debug: bool = False,
    ) -> SearchResponse:
        """Execute natural language search with full transparency.

        Args:
            raw_query: User's natural language search query
            data_dir: Directory containing markdown documentation
            max_results: Maximum number of results to return
            word_match: Enable whole word matching (passed to ripgrep as -w flag)
            include_stats: Whether to include ripgrep performance statistics
            tenant_context: Optional tenant name for context
            include_debug: Whether callers requested verbose match-trace metadata

        Returns:
            SearchResponse containing results and optional stats
        """
        # Step 1: Analyze query to extract keywords
        analyzed_query = self.query_analyzer.analyze(raw_query, tenant_context)

        logger.debug(
            f"Search query analyzed: {len(analyzed_query.normalized_tokens)} tokens, "
            f"{len(analyzed_query.extracted_keywords.technical_nouns)} nouns, "
            f"{len(analyzed_query.extracted_keywords.technical_terms)} terms"
        )

        # Step 2: Execute multi-stage search
        response = await self.search_repository.search_documents(
            analyzed_query,
            data_dir,
            max_results,
            word_match,
            include_stats,
            include_debug,
        )

        logger.debug(
            f"Search completed: {len(response.results)} results "
            f"(stage {response.results[0].match_trace.stage if response.results else 'N/A'})"
        )

        get_metrics = getattr(self.search_repository, "get_cache_metrics", None)
        metrics_snapshot: dict[str, dict[str, float | int]] = {}
        if callable(get_metrics):
            metrics_snapshot = get_metrics(data_dir)
        if metrics_snapshot:
            first_key, first_metrics = next(iter(metrics_snapshot.items()))
            logger.debug(
                "Cache metrics for %s -> hits=%s misses=%s loads=%s last_load=%.3fs",
                tenant_context or first_key,
                first_metrics.get("hits", 0),
                first_metrics.get("misses", 0),
                first_metrics.get("loads", 0),
                first_metrics.get("last_load_seconds", 0.0),
            )

        return response

    async def warm_index(self, data_dir: Path) -> None:
        """Preload search indexes asynchronously for the provided directory."""

        await self.search_repository.warm_cache(data_dir)

    async def ensure_resident(self, data_dir: Path, *, poll_interval: float | None = None) -> None:
        """Ensure the repository keeps the tenant's index resident and monitored."""

        ensure_resident = getattr(self.search_repository, "ensure_resident", None)
        if callable(ensure_resident):
            await ensure_resident(data_dir, poll_interval=poll_interval)
            return
        await self.warm_index(data_dir)

    def invalidate_cache(self, data_dir: Path | None = None) -> None:
        """Invalidate cached index data, forcing a reload on the next access."""

        self.search_repository.invalidate_cache(data_dir)

    async def stop_resident(self, data_dir: Path | None = None) -> None:
        """Stop any residency watchers and drop manifest pollers."""

        stop_resident = getattr(self.search_repository, "stop_resident", None)
        if callable(stop_resident):
            await stop_resident(data_dir)
            return
        # Fallback: best-effort cache invalidation when repository lacks residency APIs
        self.invalidate_cache(data_dir)
