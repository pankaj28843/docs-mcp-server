"""Simplified search index - deep module consolidation.

Eliminates SearchService -> IndexedSearchRepository -> BM25SearchEngine -> SqliteSegment
abstraction layers in favor of a single deep module with simple interface.

Following "A Philosophy of Software Design" Ch. 4: Deep modules hide complexity
behind simple interfaces.
"""

import json
import logging
import math
from pathlib import Path
import sqlite3

from docs_mcp_server.domain.search import MatchTrace, SearchResponse, SearchResult
from docs_mcp_server.search.analyzers import get_analyzer
from docs_mcp_server.search.schema import Schema, TextField
from docs_mcp_server.search.snippet import build_smart_snippet


logger = logging.getLogger(__name__)


class SearchIndex:
    """Deep search module with simple interface.

    Hides all implementation complexity (SQLite, BM25, analyzers, snippets)
    behind a single search() method. Eliminates 4-layer abstraction stack.
    """

    def __init__(self, db_path: Path):
        """Initialize search index with single SQLite connection."""
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)

        # Optimize SQLite for performance
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA cache_size = -64000")  # 64MB cache
        self._conn.execute("PRAGMA mmap_size = 268435456")  # 256MB mmap
        self._conn.execute("PRAGMA temp_store = MEMORY")

        # Pre-compile frequently used statements
        self._search_stmt = self._conn.prepare("""
            SELECT doc_id, title, url, content,
                   SUM(tf * idf * boost) as score
            FROM search_index
            WHERE term IN ({})
            GROUP BY doc_id
            ORDER BY score DESC
            LIMIT ?
        """)

        self._schema = self._load_schema()

    def search(self, query: str, max_results: int = 20) -> SearchResponse:
        """Search documents with BM25 scoring.

        Simple interface hiding all complexity:
        - Query analysis and tokenization
        - BM25 scoring calculation
        - Result ranking and snippet generation
        - SQLite query execution

        Args:
            query: Natural language search query
            max_results: Maximum results to return

        Returns:
            SearchResponse with ranked results
        """
        # Tokenize query using body field analyzer
        analyzer = get_analyzer("standard")
        tokens = [token.text for token in analyzer(query.lower()) if token.text]

        if not tokens:
            return SearchResponse(results=[], total_count=0)

        # Execute search with prepared statement
        placeholders = ",".join("?" * len(tokens))
        query_sql = f"""
            SELECT doc_id, title, url, content,
                   SUM(tf * idf * boost) as score
            FROM search_index
            WHERE term IN ({placeholders})
            GROUP BY doc_id
            ORDER BY score DESC
            LIMIT ?
        """

        cursor = self._conn.execute(query_sql, [*tokens, max_results])
        rows = cursor.fetchall()

        # Build results with snippets
        results = []
        for _doc_id, title, url, content, score in rows:
            snippet = build_smart_snippet(content, tokens, max_length=200)

            result = SearchResult(
                title=title,
                url=url,
                snippet=snippet,
                score=float(score),
                match_trace=MatchTrace(stage="bm25", match_reason="term_match", matched_terms=tokens),
            )
            results.append(result)

        return SearchResponse(results=results, total_count=len(results))

    def _load_schema(self) -> Schema:
        """Load search schema from database."""
        try:
            cursor = self._conn.execute("SELECT schema_json FROM metadata LIMIT 1")
            row = cursor.fetchone()
            if row:
                schema_data = json.loads(row[0])
                return Schema.from_dict(schema_data)
        except sqlite3.OperationalError:
            pass

        # Default schema if none found
        return Schema(
            text_fields=[
                TextField(name="title", analyzer_name="standard", boost=2.0),
                TextField(name="body", analyzer_name="standard", boost=1.0),
            ]
        )

    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


class _BM25Calculator:
    """Inline BM25 scoring - no separate engine class needed."""

    def __init__(self, k1: float = 1.2, b: float = 0.75):
        self.k1 = k1
        self.b = b

    def score(self, tf: int, df: int, doc_len: int, avg_doc_len: float, total_docs: int) -> float:
        """Calculate BM25 score for term."""
        # IDF calculation
        idf = math.log((total_docs - df + 0.5) / (df + 0.5))

        # TF normalization
        tf_norm = (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * (doc_len / avg_doc_len)))

        return idf * tf_norm
