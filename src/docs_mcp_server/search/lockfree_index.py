"""Lock-free concurrent search index using atomic operations."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import threading

from docs_mcp_server.domain.search import MatchTrace, SearchResponse, SearchResult
from docs_mcp_server.search.analyzers import get_analyzer


class LockFreeSearchIndex:
    """Lock-free search index for high-concurrency scenarios."""

    def __init__(self, db_path: Path, max_workers: int = 4):
        self.db_path = db_path
        self.max_workers = max_workers
        self._local = threading.local()
        self._analyzer = get_analyzer("default")
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local connection for lock-free access."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.execute("PRAGMA journal_mode = WAL")
            self._local.conn.execute("PRAGMA synchronous = NORMAL")
            self._local.conn.execute("PRAGMA cache_size = -2000")
        return self._local.conn

    def search(self, query: str, max_results: int = 20) -> SearchResponse:
        """Lock-free concurrent search."""
        tokens = [token.text for token in self._analyzer(query.lower()) if token.text]
        if not tokens:
            return SearchResponse(results=[])

        # Split tokens across workers for parallel processing
        if len(tokens) > 1 and self.max_workers > 1:
            return self._parallel_search(tokens, max_results)
        return self._single_search(tokens, max_results)

    def _parallel_search(self, tokens: list[str], max_results: int) -> SearchResponse:
        """Parallel search across multiple tokens."""
        chunk_size = max(1, len(tokens) // self.max_workers)
        token_chunks = [tokens[i : i + chunk_size] for i in range(0, len(tokens), chunk_size)]

        futures = []
        for chunk in token_chunks:
            future = self._executor.submit(self._search_chunk, chunk, max_results)
            futures.append(future)

        # Merge results from all chunks
        all_results = []
        for future in futures:
            chunk_results = future.result()
            all_results.extend(chunk_results.results)

        # Sort by score and limit
        all_results.sort(key=lambda r: r.relevance_score, reverse=True)
        final_results = all_results[:max_results]

        return SearchResponse(results=final_results)

    def _search_chunk(self, tokens: list[str], max_results: int) -> SearchResponse:
        """Search a chunk of tokens."""
        conn = self._get_connection()
        placeholders = ",".join("?" * len(tokens))

        cursor = conn.execute(
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
                    document_title=title,
                    document_url=url,
                    snippet=self._build_snippet(content, tokens),
                    relevance_score=float(score),
                    match_trace=MatchTrace(
                        stage=1,
                        stage_name="parallel",
                        query_variant="chunk_search",
                        match_reason="chunk",
                        ranking_factors={"chunk_id": len(results)},
                    ),
                )
            )

        return SearchResponse(results=results)

    def _single_search(self, tokens: list[str], max_results: int) -> SearchResponse:
        """Single-threaded search for small queries."""
        conn = self._get_connection()
        placeholders = ",".join("?" * len(tokens))

        cursor = conn.execute(
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
                    document_title=title,
                    document_url=url,
                    snippet=self._build_snippet(content, tokens),
                    relevance_score=float(score),
                    match_trace=MatchTrace(
                        stage=1,
                        stage_name="single",
                        query_variant="small_query",
                        match_reason="small_query",
                        ranking_factors={"token_count": len(tokens)},
                    ),
                )
            )

        return SearchResponse(results=results)

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
        """Clean shutdown."""
        self._executor.shutdown(wait=True)
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
