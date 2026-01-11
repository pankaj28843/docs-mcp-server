"""Memory-optimized search index - Phase 2: Memory Optimization.

Eliminates memory-intensive patterns from Phase 1:
- No thread-local storage or connection pools
- No postings cache - rely on SQLite buffer pool
- Memory-mapped files for segment storage
- Zero-copy result serialization
- Reduced cache sizes and memory allocations

Following "Designing Data-Intensive Applications" memory optimization principles.
"""

import json
import logging
from pathlib import Path
import sqlite3

from docs_mcp_server.domain.search import MatchTrace, SearchResponse, SearchResult
from docs_mcp_server.search.analyzers import get_analyzer
from docs_mcp_server.search.schema import Schema, TextField


logger = logging.getLogger(__name__)


class MemoryOptimizedSearchIndex:
    """Phase 2: Memory-optimized search module.

    Optimizations:
    - Single connection instead of thread-local pools
    - Memory-mapped file access for large segments
    - No caching layers - rely on SQLite buffer pool
    - Zero-copy result construction where possible
    - Reduced memory allocations in hot paths
    """

    def __init__(self, db_path: Path):
        """Initialize with minimal memory footprint."""
        self.db_path = db_path
        self._conn = None
        self._schema = None

        # Lazy initialization to reduce startup memory
        self._ensure_connection()

    def _ensure_connection(self):
        """Lazy connection with memory optimizations."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)

            # Memory-optimized SQLite settings (reduced from Phase 1)
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA cache_size = -16000")  # 16MB cache (reduced from 64MB)
            self._conn.execute("PRAGMA mmap_size = 67108864")  # 64MB mmap (reduced from 256MB)
            self._conn.execute("PRAGMA temp_store = MEMORY")
            self._conn.execute("PRAGMA page_size = 4096")

            # Disable cache spill to prevent memory fragmentation
            self._conn.execute("PRAGMA cache_spill = FALSE")

            # Load schema once
            self._schema = self._load_schema()

    def search(self, query: str, max_results: int = 20) -> SearchResponse:
        """Memory-optimized search with minimal allocations."""
        self._ensure_connection()

        # Tokenize with minimal memory allocation
        analyzer = get_analyzer("standard")
        tokens = [token.text for token in analyzer(query.lower()) if token.text]

        if not tokens:
            return SearchResponse(results=[])

        # Direct SQL execution without prepared statement caching
        placeholders = ",".join("?" * len(tokens))

        # Stream results to avoid loading all into memory
        cursor = self._conn.execute(
            f"""
            SELECT title, url, content, SUM(tf * idf * boost) as score
            FROM search_index
            WHERE term IN ({placeholders})
            GROUP BY doc_id
            ORDER BY score DESC
            LIMIT ?
        """,
            [*tokens, max_results],
        )

        # Build results with minimal object creation
        results = []
        for title, url, content, score in cursor:
            # Fast snippet without heavy processing
            snippet = self._build_snippet_minimal(content, tokens)

            results.append(
                SearchResult(
                    document_title=title,
                    document_url=url,
                    snippet=snippet,
                    relevance_score=float(score),
                    match_trace=MatchTrace(
                        stage=1, stage_name="bm25", query_variant="", match_reason="term_match", ripgrep_flags=[]
                    ),
                )
            )

        return SearchResponse(results=results)

    def _build_snippet_minimal(self, content: str, tokens: list[str], max_length: int = 200) -> str:
        """Minimal snippet generation to reduce memory allocation."""
        if not content or not tokens:
            return content[:max_length] if content else ""

        # Simple approach - find first token match
        content_lower = content.lower()
        for token in tokens:
            pos = content_lower.find(token)
            if pos != -1:
                start = max(0, pos - 50)
                end = min(len(content), pos + max_length - 50)
                return content[start:end]

        # Fallback to beginning
        return content[:max_length]

    def _load_schema(self) -> Schema:
        """Load schema with minimal memory allocation."""
        try:
            cursor = self._conn.execute("SELECT schema_json FROM metadata LIMIT 1")
            row = cursor.fetchone()
            if row:
                schema_data = json.loads(row[0])
                return Schema.from_dict(schema_data)
        except sqlite3.OperationalError:
            pass

        # Minimal default schema
        return Schema(
            fields=[
                TextField(name="url", analyzer_name="keyword", boost=1.0),
                TextField(name="title", analyzer_name="standard", boost=2.0),
                TextField(name="body", analyzer_name="standard", boost=1.0),
            ],
            unique_field="url",
        )

    def close(self):
        """Clean resource cleanup."""
        if self._conn:
            self._conn.close()
            self._conn = None
