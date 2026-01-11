"""SIMD-optimized BM25 scoring for maximum performance."""

from pathlib import Path
import sqlite3


try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

from docs_mcp_server.domain.search import MatchTrace, SearchResponse, SearchResult
from docs_mcp_server.search.analyzers import get_analyzer


class SIMDSearchIndex:
    """SIMD-vectorized search index for maximum performance."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA cache_size = -4000")
        self._conn.execute("PRAGMA mmap_size = 16777216")
        self._analyzer = get_analyzer("standard")

    def search(self, query: str, max_results: int = 20) -> SearchResponse:
        """SIMD-optimized search with vectorized BM25 scoring."""
        tokens = [token.text for token in self._analyzer(query.lower()) if token.text]
        if not tokens:
            return SearchResponse(results=[], total_count=0)

        # Get raw data for vectorization
        placeholders = ",".join("?" * len(tokens))
        cursor = self._conn.execute(
            f"""
            SELECT title, url, content, tf, idf, boost, doc_len, avg_doc_len
            FROM search_index_raw
            WHERE term IN ({placeholders})
        """,
            tokens,
        )

        rows = cursor.fetchall()
        if not rows or not HAS_NUMPY:
            return self._fallback_search(tokens, max_results)

        # Vectorized BM25 calculation
        tf_array = np.array([row[3] for row in rows], dtype=np.float32)
        idf_array = np.array([row[4] for row in rows], dtype=np.float32)
        boost_array = np.array([row[5] for row in rows], dtype=np.float32)
        doc_len_array = np.array([row[6] for row in rows], dtype=np.float32)
        avg_doc_len = rows[0][7]

        # SIMD BM25 calculation
        k1, b = 1.2, 0.75
        tf_norm = (tf_array * (k1 + 1)) / (tf_array + k1 * (1 - b + b * (doc_len_array / avg_doc_len)))
        scores = idf_array * tf_norm * boost_array

        # Get top results
        top_indices = np.argpartition(scores, -max_results)[-max_results:]
        top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

        results = []
        for idx in top_indices:
            row = rows[idx]
            results.append(
                SearchResult(
                    title=row[0],
                    url=row[1],
                    snippet=self._build_snippet(row[2], tokens),
                    score=float(scores[idx]),
                    match_trace=MatchTrace(stage="simd", match_reason="vectorized", matched_terms=tokens),
                )
            )

        return SearchResponse(results=results, total_count=len(results))

    def _fallback_search(self, tokens: list[str], max_results: int) -> SearchResponse:
        """Fallback to standard search when SIMD unavailable."""
        placeholders = ",".join("?" * len(tokens))
        cursor = self._conn.execute(
            f"""
            SELECT title, url, content, SUM(tf * idf * boost) as score
            FROM search_index WHERE term IN ({placeholders})
            GROUP BY doc_id ORDER BY score DESC LIMIT ?
        """,
            [*tokens, max_results],
        )

        results = []
        for title, url, content, score in cursor:
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=self._build_snippet(content, tokens),
                    score=float(score),
                    match_trace=MatchTrace(stage="fallback", match_reason="no_simd", matched_terms=tokens),
                )
            )

        return SearchResponse(results=results, total_count=len(results))

    def _build_snippet(self, content: str, tokens: list[str]) -> str:
        """Fast snippet generation."""
        if not content or not tokens:
            return content[:200] if content else ""

        content_lower = content.lower()
        for token in tokens:
            pos = content_lower.find(token)
            if pos != -1:
                start = max(0, pos - 50)
                end = min(len(content), pos + 150)
                return content[start:end]
        return content[:200]

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
