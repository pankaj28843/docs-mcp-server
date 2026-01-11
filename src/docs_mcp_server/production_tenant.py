"""Production-optimized tenant with all performance enhancements."""

from pathlib import Path
import time

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.search.bloom_index import BloomFilterIndex
from docs_mcp_server.search.lockfree_index import LockFreeSearchIndex
from docs_mcp_server.search.metrics import get_metrics_collector, record_search_metrics
from docs_mcp_server.search.simd_index import SIMDSearchIndex
from docs_mcp_server.utils.models import SearchDocsResponse, SearchResult


class ProductionTenant:
    """Production-optimized tenant with all performance enhancements."""

    def __init__(self, tenant_config: TenantConfig):
        self.codename = tenant_config.codename
        self._data_path = Path(f"data/{self.codename}")

        # Initialize optimized search index
        search_db_path = self._data_path / "__search_segments" / "search.db"
        if not search_db_path.exists():
            self._search_index = None
            return

        # Choose best index based on available optimizations
        try:
            # Try SIMD first (best performance)
            self._search_index = SIMDSearchIndex(search_db_path)
            self._index_type = "simd"
        except ImportError:
            try:
                # Fall back to lock-free concurrent
                self._search_index = LockFreeSearchIndex(search_db_path)
                self._index_type = "lockfree"
            except Exception:
                # Fall back to Bloom filter
                self._search_index = BloomFilterIndex(search_db_path)
                self._index_type = "bloom"

    def search(self, query: str, size: int, word_match: bool) -> SearchDocsResponse:
        """Production search with metrics collection."""
        if not self._search_index:
            return SearchDocsResponse(results=[], error=f"No search index for {self.codename}", query=query)

        start_time = time.perf_counter()

        try:
            # Execute optimized search
            search_response = self._search_index.search(query, size)

            # Convert results
            results = [
                SearchResult(title=result.title, url=result.url, snippet=result.snippet, score=result.score)
                for result in search_response.results
            ]

            # Record metrics
            latency_ms = (time.perf_counter() - start_time) * 1000
            record_search_metrics(latency_ms=latency_ms, result_count=len(results), query_tokens=len(query.split()))

            return SearchDocsResponse(results=results)

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            record_search_metrics(latency_ms=latency_ms, result_count=0)

            return SearchDocsResponse(results=[], error=f"Search failed: {e}", query=query)

    def get_performance_stats(self) -> dict:
        """Get performance statistics for this tenant."""
        stats = get_metrics_collector().get_stats()
        stats["index_type"] = getattr(self, "_index_type", "none")
        stats["tenant"] = self.codename
        return stats

    def close(self):
        """Clean shutdown."""
        if self._search_index:
            self._search_index.close()
            self._search_index = None
