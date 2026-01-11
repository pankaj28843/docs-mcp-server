"""Bloom filter optimized search index for negative query filtering."""

import hashlib
from pathlib import Path
import sqlite3

from docs_mcp_server.domain.search import MatchTrace, SearchResponse, SearchResult
from docs_mcp_server.search.analyzers import get_analyzer


class BloomFilterIndex:
    """Search index with Bloom filter for fast negative query detection."""

    def __init__(self, db_path: Path, bloom_size: int = 1000000):
        self.db_path = db_path
        self.bloom_size = bloom_size
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA cache_size = -4000")
        self._analyzer = get_analyzer("standard")

        # Initialize Bloom filter
        self._bloom_filter = bytearray(bloom_size // 8)
        self._build_bloom_filter()

    def _build_bloom_filter(self):
        """Build Bloom filter from existing terms."""
        cursor = self._conn.execute("SELECT DISTINCT term FROM search_index")
        for (term,) in cursor:
            self._add_to_bloom(term)

    def _add_to_bloom(self, term: str):
        """Add term to Bloom filter."""
        for i in range(3):  # 3 hash functions
            hash_val = int(hashlib.md5(f"{term}{i}".encode()).hexdigest(), 16)
            bit_pos = hash_val % (self.bloom_size)
            byte_pos = bit_pos // 8
            bit_offset = bit_pos % 8
            self._bloom_filter[byte_pos] |= 1 << bit_offset

    def _might_exist(self, term: str) -> bool:
        """Check if term might exist using Bloom filter."""
        for i in range(3):  # 3 hash functions
            hash_val = int(hashlib.md5(f"{term}{i}".encode()).hexdigest(), 16)
            bit_pos = hash_val % (self.bloom_size)
            byte_pos = bit_pos // 8
            bit_offset = bit_pos % 8
            if not (self._bloom_filter[byte_pos] & (1 << bit_offset)):
                return False
        return True

    def search(self, query: str, max_results: int = 20) -> SearchResponse:
        """Bloom filter optimized search."""
        tokens = [token.text for token in self._analyzer(query.lower()) if token.text]
        if not tokens:
            return SearchResponse(results=[], total_count=0)

        # Filter tokens using Bloom filter
        existing_tokens = [token for token in tokens if self._might_exist(token)]

        if not existing_tokens:
            # Fast negative response - no tokens exist
            return SearchResponse(results=[], total_count=0)

        # Search with filtered tokens
        placeholders = ",".join("?" * len(existing_tokens))
        cursor = self._conn.execute(
            f"""
            SELECT title, url, content, SUM(tf * idf * boost) as score
            FROM search_index WHERE term IN ({placeholders})
            GROUP BY doc_id ORDER BY score DESC LIMIT ?
        """,
            [*existing_tokens, max_results],
        )

        results = []
        for title, url, content, score in cursor:
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=self._build_snippet(content, existing_tokens),
                    score=float(score),
                    match_trace=MatchTrace(
                        stage="bloom_filtered",
                        match_reason=f"filtered_{len(tokens) - len(existing_tokens)}_terms",
                        matched_terms=existing_tokens,
                    ),
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
