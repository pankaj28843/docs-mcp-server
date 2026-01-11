"""Segment-based search index implementation.

Works with the existing segment database format that has documents and postings tables.
Provides BM25 scoring and snippet generation with optional SIMD optimization.
"""

import json
import logging
import math
from pathlib import Path
import sqlite3

from docs_mcp_server.domain.search import MatchTrace, SearchResponse, SearchResult as DomainSearchResult
from docs_mcp_server.search.analyzers import get_analyzer
from docs_mcp_server.search.snippet import build_smart_snippet


# Optional SIMD optimization
try:
    from docs_mcp_server.search.simd_bm25 import SIMDBm25Calculator

    SIMD_AVAILABLE = True
except ImportError:
    SIMD_AVAILABLE = False


logger = logging.getLogger(__name__)


class SegmentSearchIndex:
    """Search index that works with segment database format.

    Uses documents and postings tables to perform BM25 search with optional SIMD optimization.
    """

    def __init__(self, db_path: Path, enable_simd: bool | None = None):
        """Initialize search index with segment database."""
        self.db_path = db_path
        self._conn = None
        self._total_docs = 0
        self._avg_doc_length = 1000.0

        # SIMD optimization (enabled by default for performance)
        if enable_simd is None:
            enable_simd = True  # Default to enabled for maximum performance

        self._simd_enabled = enable_simd and SIMD_AVAILABLE
        if self._simd_enabled:
            self._simd_calculator = SIMDBm25Calculator()
            logger.info("SIMD optimization enabled for BM25 calculations")
        else:
            self._simd_calculator = None
            if enable_simd and not SIMD_AVAILABLE:
                logger.warning("SIMD requested but not available, using scalar fallback")

        # Initialize connection and cache
        self._initialize_connection()

    def _initialize_connection(self):
        """Initialize database connection with optimizations."""
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0,  # 30 second timeout
        )

        # Optimize SQLite for performance
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA cache_size = -64000")  # 64MB cache
        self._conn.execute("PRAGMA mmap_size = 268435456")  # 256MB mmap
        self._conn.execute("PRAGMA temp_store = MEMORY")
        self._conn.execute("PRAGMA query_only = 1")  # Read-only mode for safety

        # Cache document count for BM25 calculations
        self._total_docs = self._get_total_document_count()
        self._avg_doc_length = self._get_average_document_length()

        # Prepare frequently used statements for better performance
        self._prepare_statements()

    def search(self, query: str, max_results: int = 20) -> SearchResponse:
        """Search documents with BM25 scoring.

        Args:
            query: Natural language search query
            max_results: Maximum results to return

        Returns:
            SearchResponse with ranked results
        """
        # Tokenize query
        analyzer = get_analyzer("default")
        tokens = [token.text for token in analyzer(query.lower()) if token.text]

        if not tokens:
            return SearchResponse(results=[])

        # Get document scores using BM25
        doc_scores = self._calculate_bm25_scores(tokens)

        # Sort by score and limit results
        sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)[:max_results]

        # Build results with document data and snippets
        results = []
        for doc_id, score in sorted_docs:
            doc_data = self._get_document_data(doc_id)
            if doc_data:
                snippet = build_smart_snippet(doc_data.get("body", ""), tokens, max_chars=200)

                result = DomainSearchResult(
                    document_url=doc_data.get("url", doc_id),
                    document_title=doc_data.get("title", ""),
                    snippet=snippet,
                    relevance_score=float(score),
                    match_trace=MatchTrace(
                        stage=1, stage_name="bm25", query_variant="", match_reason="term_match", ripgrep_flags=[]
                    ),
                )
                results.append(result)

        return SearchResponse(results=results)

    def _prepare_statements(self):
        """Prepare frequently used SQL statements for better performance."""
        # Pre-compile frequently used queries (SQLite will cache these automatically)
        # This is more about organizing the queries than actual prepared statements
        self._postings_query = "SELECT doc_id, tf FROM postings WHERE field = ? AND term = ?"
        self._postings_fallback_query = "SELECT doc_id FROM postings WHERE field = ? AND term = ?"
        self._doc_data_query = "SELECT field_data FROM documents WHERE doc_id = ?"
        self._doc_length_query = "SELECT length FROM field_lengths WHERE doc_id = ? AND field = 'body'"

    def _calculate_bm25_scores(self, tokens: list[str]) -> dict[str, float]:
        """Calculate BM25 scores using SIMD optimization when available (enabled by default)."""
        if self._simd_enabled and len(tokens) > 1:
            return self._calculate_bm25_scores_simd(tokens)
        return self._calculate_bm25_scores_scalar(tokens)

    def _calculate_bm25_scores_simd(self, tokens: list[str]) -> dict[str, float]:
        """Calculate BM25 scores using SIMD vectorization."""
        # Collect all postings data first
        all_postings = {}
        term_dfs = {}

        for token in tokens:
            try:
                cursor = self._conn.execute(self._postings_query, ("body", token))
                postings = cursor.fetchall()
            except sqlite3.OperationalError:
                cursor = self._conn.execute(self._postings_fallback_query, ("body", token))
                postings = [(doc_id, 1) for (doc_id,) in cursor.fetchall()]

            if postings:
                all_postings[token] = postings
                term_dfs[token] = len(postings)

        if not all_postings:
            return {}

        # Collect unique documents and their data
        doc_data = {}
        for token, postings in all_postings.items():
            for doc_id, tf in postings:
                if doc_id not in doc_data:
                    doc_data[doc_id] = {"terms": {}, "length": self._get_document_length(doc_id)}
                doc_data[doc_id]["terms"][token] = tf

        # Prepare data for vectorized calculation
        doc_scores = {}
        for doc_id, data in doc_data.items():
            term_frequencies = []
            doc_frequencies = []
            doc_lengths = []

            for token in data["terms"]:
                term_frequencies.append(data["terms"][token])
                doc_frequencies.append(term_dfs[token])
                doc_lengths.append(data["length"])

            # Use SIMD calculator for this document's terms
            if len(term_frequencies) > 0:
                scores = self._simd_calculator.calculate_scores_vectorized(
                    term_frequencies, doc_frequencies, doc_lengths, self._avg_doc_length, self._total_docs
                )
                doc_scores[doc_id] = sum(scores)

        return doc_scores

    def _calculate_bm25_scores_scalar(self, tokens: list[str]) -> dict[str, float]:
        """Calculate BM25 scores using scalar operations (fallback)."""
        doc_scores = {}

        for token in tokens:
            # Get postings for this term from body field with proper TF
            try:
                cursor = self._conn.execute(self._postings_query, ("body", token))
                postings = cursor.fetchall()
            except sqlite3.OperationalError:
                # Fallback to simple query if tf column doesn't exist
                cursor = self._conn.execute(self._postings_fallback_query, ("body", token))
                postings = [(doc_id, 1) for (doc_id,) in cursor.fetchall()]

            if not postings:
                continue

            # Calculate IDF for this term
            df = len(postings)  # Document frequency
            idf = math.log((self._total_docs - df + 0.5) / (df + 0.5))

            # Calculate TF-IDF for each document
            for doc_id, tf in postings:
                # Get actual document length
                doc_length = self._get_document_length(doc_id)

                # BM25 calculation with proper TF
                k1 = 1.2
                b = 0.75
                tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (doc_length / self._avg_doc_length)))

                score = idf * tf_norm

                if doc_id in doc_scores:
                    doc_scores[doc_id] += score
                else:
                    doc_scores[doc_id] = score

        return doc_scores

    def _get_document_length(self, doc_id: str) -> float:
        """Get actual document length from field_lengths table."""
        try:
            cursor = self._conn.execute(self._doc_length_query, (doc_id,))
            row = cursor.fetchone()
            if row:
                return float(row[0])
        except sqlite3.OperationalError:
            # field_lengths table might not exist
            pass

        # Fallback to average length
        return self._avg_doc_length

    def _get_document_data(self, doc_id: str) -> dict | None:
        """Get document data from documents table."""
        cursor = self._conn.execute(self._doc_data_query, (doc_id,))
        row = cursor.fetchone()

        if row:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                logger.error(f"Failed to parse document data for {doc_id}")
                return None

        return None

    def _get_total_document_count(self) -> int:
        """Get total number of documents."""
        cursor = self._conn.execute("SELECT COUNT(*) FROM documents")
        row = cursor.fetchone()
        return row[0] if row else 0

    def _get_average_document_length(self) -> float:
        """Get average document length from field_lengths table."""
        try:
            cursor = self._conn.execute("SELECT AVG(length) FROM field_lengths WHERE field = 'body'")
            row = cursor.fetchone()
            if row and row[0] is not None:
                return float(row[0])
        except sqlite3.OperationalError:
            # field_lengths table might not exist
            pass

        # Fallback to reasonable default
        return 1000.0

    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def get_performance_info(self) -> dict:
        """Get performance information including optimization status."""
        info = {
            "total_documents": self._total_docs,
            "avg_document_length": self._avg_doc_length,
            "simd_enabled": self._simd_enabled,
            "optimization_level": "simd_vectorized" if self._simd_enabled else "scalar_baseline",
        }

        if self._simd_calculator:
            info.update(self._simd_calculator.get_performance_info())

        return info
