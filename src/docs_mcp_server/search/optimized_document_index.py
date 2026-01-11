"""Optimized Document Index - Unified Search Interface.

Provides a unified interface for document search using the segment search index.
Eliminates interface proliferation while maintaining clean architecture.

Design Principles:
- Single interface hiding implementation complexity
- Deep module: powerful functionality, simple interface
- Production-ready segment search implementation
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

from docs_mcp_server.domain.search import SearchResponse
from docs_mcp_server.search.segment_search_index import SegmentSearchIndex


logger = logging.getLogger(__name__)


@runtime_checkable
class DocumentIndexProtocol(Protocol):
    """Unified protocol for document index implementations."""

    def search(self, query: str, max_results: int = 20) -> SearchResponse:
        """Search documents and return ranked results."""
        ...

    def close(self) -> None:
        """Clean up resources."""
        ...


class OptimizedDocumentIndex:
    """Unified document index using production-ready segment search.

    Provides a single interface that uses the segment search index implementation.
    Hides all implementation details from clients.
    """

    def __init__(self, db_path: Path):
        """Initialize with segment search index.

        Args:
            db_path: Path to SQLite search database
        """
        self.db_path = db_path
        self._index_implementation = self._create_search_index()

        logger.info("OptimizedDocumentIndex using segment search implementation")

    def _create_search_index(self) -> DocumentIndexProtocol:
        """Create segment search index implementation."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Search database not found: {self.db_path}")

        return SegmentSearchIndex(self.db_path)

    def search(self, query: str, max_results: int = 20) -> SearchResponse:
        """Search documents using segment search implementation.

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            SearchResponse with ranked results
        """
        return self._index_implementation.search(query, max_results)

    def get_optimization_info(self) -> dict:
        """Get information about active implementation."""
        return {
            "optimization_type": "segment",
            "implementation_class": type(self._index_implementation).__name__,
            "db_path": str(self.db_path),
        }

    def close(self) -> None:
        """Clean up resources."""
        if self._index_implementation:
            self._index_implementation.close()


def create_optimized_document_index(db_path: Path) -> OptimizedDocumentIndex:
    """Factory function for creating optimized document indexes.

    Args:
        db_path: Path to search database

    Returns:
        OptimizedDocumentIndex with segment search implementation
    """
    return OptimizedDocumentIndex(db_path)
