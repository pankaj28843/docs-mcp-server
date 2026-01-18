"""Segment-based search index implementation.

Works with the existing segment database format that has documents and postings tables.
Provides BM25 scoring and snippet generation with optional SIMD optimization.
"""

import logging
import math
from pathlib import Path
import sqlite3

from opentelemetry.trace import SpanKind

from docs_mcp_server.domain.search import MatchTrace, SearchResponse, SearchResult as DomainSearchResult
from docs_mcp_server.observability import SEARCH_LATENCY, track_latency
from docs_mcp_server.observability.tracing import create_span
from docs_mcp_server.search.analyzers import get_analyzer
from docs_mcp_server.search.bloom_filter import bloom_positions
from docs_mcp_server.search.bm25_engine import BM25SearchEngine
from docs_mcp_server.search.schema import Schema
from docs_mcp_server.search.snippet import build_smart_snippet
from docs_mcp_server.search.sqlite_pragmas import apply_read_pragmas
from docs_mcp_server.search.sqlite_storage import SqliteSegment, SqliteSegmentStore


# Optional optimizations
try:
    from docs_mcp_server.search.simd_bm25 import SIMDBm25Calculator

    SIMD_AVAILABLE = True
except ImportError:
    SIMD_AVAILABLE = False

try:
    from docs_mcp_server.search.lockfree_concurrent import LockFreeConcurrentSearch

    LOCKFREE_AVAILABLE = True
except ImportError:
    LOCKFREE_AVAILABLE = False


logger = logging.getLogger(__name__)
_SQLITE_MAX_VARIABLES = 999


class SegmentSearchIndex:
    """Search index that works with segment database format.

    Uses documents and postings tables to perform BM25 search with optional SIMD optimization.
    """

    def __init__(
        self,
        db_path: Path,
        tenant: str | None = None,
        enable_simd: bool | None = None,
        enable_lockfree: bool | None = None,
        enable_bloom_filter: bool | None = None,
    ):
        """Initialize search index with segment database."""
        self.db_path = db_path
        self.tenant = tenant
        self._conn = None
        self._avg_doc_length_fallback = 1000.0

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

        # Lock-free concurrency (enabled by default for performance)
        if enable_lockfree is None:
            enable_lockfree = True  # Default to enabled for maximum performance

        self._lockfree_enabled = enable_lockfree and LOCKFREE_AVAILABLE
        if self._lockfree_enabled:
            self._concurrent_search = LockFreeConcurrentSearch(db_path)
            logger.info("Lock-free concurrency enabled for search operations")
        else:
            self._concurrent_search = None
            if enable_lockfree and not LOCKFREE_AVAILABLE:
                logger.warning("Lock-free requested but not available, using standard connections")

        if enable_bloom_filter is None:
            enable_bloom_filter = True

        self._bloom_enabled = bool(enable_bloom_filter)
        if self._bloom_enabled:
            logger.info("SQLite-resident bloom filter enabled for query term filtering")

        # Initialize connection and prepared statements
        self._initialize_connection()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure resources are cleaned up."""
        self.close()

    def _initialize_connection(self):
        """Initialize database connection with optimizations."""
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0,  # 30 second timeout
            cached_statements=0,
        )
        apply_read_pragmas(self._conn)

        # Prepare frequently used statements for better performance
        self._prepare_statements()

    def _execute_query(self, query: str, params: tuple = ()) -> list:
        """Execute query using lock-free concurrency when available."""
        if self._lockfree_enabled:
            return self._concurrent_search.execute_concurrent_query(query, params)
        cursor = self._conn.execute(query, params)
        return cursor.fetchall()

    def _execute_single_query(self, query: str, params: tuple = ()) -> tuple | None:
        """Execute query returning single result using lock-free concurrency when available."""
        if self._lockfree_enabled:
            results = self._concurrent_search.execute_concurrent_query(query, params)
            return results[0] if results else None
        cursor = self._conn.execute(query, params)
        return cursor.fetchone()

    def search(self, query: str, max_results: int = 20) -> SearchResponse:
        """Search documents with BM25 scoring."""
        with (
            create_span(
                "search.query",
                kind=SpanKind.INTERNAL,
                attributes={"search.query": query[:100], "search.max_results": max_results},
            ) as span,
            track_latency(SEARCH_LATENCY, tenant=self.tenant or "default"),
        ):
            if not query or not query.strip():
                span.set_attribute("search.result_count", 0)
                return SearchResponse(results=[])

            segment = self._load_segment_for_scoring()
            if segment is not None:
                try:
                    response = self._search_with_engine(segment, query, max_results)
                finally:
                    segment.close()
                span.set_attribute("search.result_count", len(response.results))
                return response

            analyzer = get_analyzer("default")
            tokens = [token.text for token in analyzer(query.lower()) if token.text]

            if not tokens:
                span.set_attribute("search.result_count", 0)
                return SearchResponse(results=[])

            tokens = self._filter_tokens_with_bloom(tokens)
            if not tokens:
                span.set_attribute("search.result_count", 0)
                return SearchResponse(results=[])

            doc_scores = self._calculate_bm25_scores(tokens)
            sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)[:max_results]

            results = []
            doc_ids = [doc_id for doc_id, _score in sorted_docs]
            doc_lookup = self._get_documents_data(doc_ids)
            for doc_id, score in sorted_docs:
                doc_data = doc_lookup.get(doc_id)
                if doc_data:
                    snippet_source = doc_data.get("body") or doc_data.get("excerpt", "")
                    snippet = build_smart_snippet(snippet_source, tokens, max_chars=200)
                    result = DomainSearchResult(
                        document_url=doc_data.get("url", doc_id),
                        document_title=doc_data.get("title", ""),
                        snippet=snippet,
                        relevance_score=float(score),
                        match_trace=MatchTrace(
                            stage=1,
                            stage_name="bm25",
                            query_variant="",
                            match_reason="term_match",
                            ripgrep_flags=[],
                        ),
                    )
                    results.append(result)

            span.set_attribute("search.result_count", len(results))
            return SearchResponse(results=results)

    def _search_with_engine(self, segment: SqliteSegment, query: str, max_results: int) -> SearchResponse:
        """Search using the BM25 engine with full feature flags enabled."""
        if max_results <= 0:
            return SearchResponse(results=[])

        engine = BM25SearchEngine(
            segment.schema,
            field_boosts=self._resolve_field_boosts(segment.schema),
            enable_phrase_bonus=True,
            enable_fuzzy=True,
        )
        token_context = engine.tokenize_query(query)
        if token_context.is_empty():
            return SearchResponse(results=[])

        ranked = engine.score(segment, token_context, limit=max_results)
        highlight_terms = list(token_context.ordered_terms)

        results: list[DomainSearchResult] = []
        for ranked_doc in ranked:
            doc_fields = segment.get_document(ranked_doc.doc_id)
            if not doc_fields:
                continue
            snippet_source = doc_fields.get("body") or doc_fields.get("excerpt") or doc_fields.get("title") or ""
            snippet = build_smart_snippet(snippet_source, highlight_terms, max_chars=200)
            results.append(
                DomainSearchResult(
                    document_url=doc_fields.get("url", ranked_doc.doc_id),
                    document_title=doc_fields.get("title", ""),
                    snippet=snippet,
                    relevance_score=float(ranked_doc.score),
                    match_trace=MatchTrace(
                        stage=5,
                        stage_name="bm25f",
                        query_variant=" ".join(highlight_terms)[:100],
                        match_reason="BM25F ranking via SQLite segments",
                        ripgrep_flags=[],
                    ),
                )
            )

        return SearchResponse(results=results)

    def _load_segment_for_scoring(self) -> SqliteSegment | None:
        store = SqliteSegmentStore(self.db_path.parent)
        return store.load(self.db_path.stem)

    def _prepare_statements(self):
        """Prepare frequently used SQL statements for better performance."""
        # Pre-compile frequently used queries (SQLite will cache these automatically)
        # This is more about organizing the queries than actual prepared statements
        self._postings_query = "SELECT doc_id, tf, doc_length FROM postings WHERE field = ? AND term = ?"
        self._doc_data_query = (
            "SELECT url, title, body, excerpt, headings, headings_h1, headings_h2, "
            "url_path, path, tags, language, timestamp "
            "FROM documents WHERE doc_id = ?"
        )
        self._doc_data_by_url_query = (
            "SELECT url, title, body, excerpt, headings, headings_h1, headings_h2, "
            "url_path, path, tags, language, timestamp "
            "FROM documents WHERE url = ?"
        )

    def _calculate_bm25_scores(self, tokens: list[str]) -> dict[str, float]:
        """Calculate BM25 scores using SIMD optimization when available (enabled by default)."""
        total_docs, avg_doc_length = self._get_corpus_stats()
        if total_docs <= 0:
            return {}
        if self._simd_enabled and len(tokens) > 1:
            return self._calculate_bm25_scores_simd(tokens, total_docs, avg_doc_length)
        return self._calculate_bm25_scores_scalar(tokens, total_docs, avg_doc_length)

    def _calculate_bm25_scores_simd(
        self, tokens: list[str], total_docs: int, avg_doc_length: float
    ) -> dict[str, float]:
        """Calculate BM25 scores using SIMD vectorization."""
        # Collect all postings data first
        all_postings = {}
        term_dfs = {}

        for token in tokens:
            postings = self._execute_query(self._postings_query, ("body", token))

            if postings:
                all_postings[token] = postings
                term_dfs[token] = len(postings)

        if not all_postings:
            return {}

        # Collect unique documents and their data
        doc_data = {}
        default_length = avg_doc_length
        for token, postings in all_postings.items():
            for doc_id, tf, doc_length in postings:
                if doc_id not in doc_data:
                    doc_data[doc_id] = {"terms": {}, "length": doc_length or default_length}
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
                    term_frequencies, doc_frequencies, doc_lengths, avg_doc_length, total_docs
                )
                doc_scores[doc_id] = sum(scores)

        return doc_scores

    def _calculate_bm25_scores_scalar(
        self, tokens: list[str], total_docs: int, avg_doc_length: float
    ) -> dict[str, float]:
        """Calculate BM25 scores using scalar operations (fallback)."""
        doc_scores = {}

        default_length = avg_doc_length
        for token in tokens:
            # Get postings for this term from body field with proper TF
            postings = self._execute_query(self._postings_query, ("body", token))

            if not postings:
                continue

            # Calculate IDF for this term
            df = len(postings)  # Document frequency
            idf = math.log((total_docs - df + 0.5) / (df + 0.5))

            # Calculate TF-IDF for each document
            for doc_id, tf, doc_length in postings:
                # Get actual document length
                doc_length_value = doc_length or default_length

                # BM25 calculation with proper TF
                k1 = 1.2
                b = 0.75
                tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (doc_length_value / avg_doc_length)))

                score = idf * tf_norm

                if doc_id in doc_scores:
                    doc_scores[doc_id] += score
                else:
                    doc_scores[doc_id] = score

        return doc_scores

    def _filter_tokens_with_bloom(self, tokens: list[str]) -> list[str]:
        """Filter tokens using SQLite-resident bloom filter blocks."""
        if not self._bloom_enabled:
            return tokens

        rows = self._execute_query(
            "SELECT key, value FROM metadata WHERE key IN ('bloom_bit_size', 'bloom_hash_count', 'bloom_block_bits')"
        )
        metadata = {row[0]: row[1] for row in rows}
        if not metadata:
            raise RuntimeError("Segment metadata missing bloom settings; reindex required")

        bit_size = int(metadata.get("bloom_bit_size") or 0)
        hash_count = int(metadata.get("bloom_hash_count") or 0)
        block_bits = int(metadata.get("bloom_block_bits") or 0)

        if bit_size <= 0 or hash_count <= 0 or block_bits <= 0:
            return tokens

        term_masks: dict[str, list[tuple[int, int]]] = {}
        required_blocks: set[int] = set()

        for term in dict.fromkeys(tokens):
            positions = bloom_positions(term.lower(), bit_size, hash_count)
            masks = []
            for position in positions:
                block_index = position // block_bits
                bit_offset = position % block_bits
                mask = 1 << bit_offset
                masks.append((block_index, mask))
                required_blocks.add(block_index)
            term_masks[term] = masks

        if not required_blocks:
            return tokens

        block_list = sorted(required_blocks)
        if any((not isinstance(block, int)) or block < 0 for block in block_list):
            raise ValueError("Invalid bloom block index")
        if len(block_list) > _SQLITE_MAX_VARIABLES:
            raise ValueError("Too many bloom blocks requested")

        placeholders = ", ".join("?" for _ in block_list)
        rows = self._execute_query(
            f"SELECT block_index, bits FROM bloom_blocks WHERE block_index IN ({placeholders})",
            tuple(block_list),
        )
        blocks = {row[0]: row[1] for row in rows}

        allowed_terms = {
            term
            for term, masks in term_masks.items()
            if all((blocks.get(block_index, 0) & mask) != 0 for block_index, mask in masks)
        }
        return [term for term in tokens if term in allowed_terms]

    def _get_corpus_stats(self) -> tuple[int, float]:
        """Get total docs and average body length from metadata."""
        rows = self._execute_query("SELECT key, value FROM metadata WHERE key IN ('doc_count', 'body_total_terms')")
        metadata = {row[0]: row[1] for row in rows}
        if "doc_count" not in metadata or "body_total_terms" not in metadata:
            raise RuntimeError("Segment metadata missing doc_count/body_total_terms; reindex required")
        total_docs = int(metadata["doc_count"] or 0)
        total_terms = int(metadata["body_total_terms"] or 0)
        if total_docs <= 0:
            return 0, self._avg_doc_length_fallback
        avg_length = total_terms / total_docs
        return total_docs, avg_length

    def _get_documents_data(self, doc_ids: list[str]) -> dict[str, dict]:
        """Fetch document fields for a batch of doc_ids."""
        if not doc_ids:
            return {}
        if any(not isinstance(doc_id, str) for doc_id in doc_ids):
            raise ValueError("Invalid doc_id type")
        if len(doc_ids) > _SQLITE_MAX_VARIABLES:
            raise ValueError("Too many doc_ids requested")
        placeholders = ", ".join("?" for _ in doc_ids)
        query = (
            "SELECT doc_id, url, title, body, excerpt, headings, headings_h1, headings_h2, "
            "url_path, path, tags, language, timestamp "
            f"FROM documents WHERE doc_id IN ({placeholders})"
        )
        rows = self._execute_query(query, tuple(doc_ids))
        results: dict[str, dict] = {}
        keys = (
            "url",
            "title",
            "body",
            "excerpt",
            "headings",
            "headings_h1",
            "headings_h2",
            "url_path",
            "path",
            "tags",
            "language",
            "timestamp",
        )
        for row in rows:
            doc_id = row[0]
            values = row[1:]
            results[doc_id] = {key: value for key, value in zip(keys, values, strict=False) if value not in (None, "")}
        return results

    def _get_document_data(self, doc_id: str) -> dict | None:
        """Get document data from documents table."""
        row = self._execute_single_query(self._doc_data_query, (doc_id,))

        if row:
            keys = (
                "url",
                "title",
                "body",
                "excerpt",
                "headings",
                "headings_h1",
                "headings_h2",
                "url_path",
                "path",
                "tags",
                "language",
                "timestamp",
            )
            doc_fields = {key: value for key, value in zip(keys, row, strict=False) if value not in (None, "")}
            return doc_fields

        return None

    def get_document_by_url(self, url: str) -> dict | None:
        """Get document data from documents table by canonical URL."""
        if not url:
            return None
        row = self._execute_single_query(self._doc_data_by_url_query, (url,))
        if not row:
            return None
        keys = (
            "url",
            "title",
            "body",
            "excerpt",
            "headings",
            "headings_h1",
            "headings_h2",
            "url_path",
            "path",
            "tags",
            "language",
            "timestamp",
        )
        return {key: value for key, value in zip(keys, row, strict=False) if value not in (None, "")}

    def _resolve_field_boosts(self, schema: Schema) -> dict[str, float]:
        return {field.name: schema.get_boost(field.name) for field in schema.fields}

    def _get_total_document_count(self) -> int:
        """Get total number of documents."""
        row = self._execute_single_query("SELECT COUNT(*) FROM documents")
        return row[0] if row else 0

    def _get_average_document_length(self) -> float:
        """Get average document length from documents table."""
        _, avg_length = self._get_corpus_stats()
        return avg_length

    def close(self):
        """Close database connection and concurrent search."""
        if self._conn:
            self._conn.close()
            self._conn = None
        if self._concurrent_search:
            self._concurrent_search.close()

    def get_performance_info(self) -> dict:
        """Get performance information including optimization status."""
        total_docs, avg_length = self._get_corpus_stats()
        info = {
            "total_documents": total_docs,
            "avg_document_length": avg_length,
            "simd_enabled": self._simd_enabled,
            "lockfree_enabled": self._lockfree_enabled,
            "bloom_enabled": self._bloom_enabled,
            "optimization_level": "fully_optimized"
            if (self._simd_enabled and self._lockfree_enabled)
            else "simd_vectorized"
            if self._simd_enabled
            else "lockfree_concurrent"
            if self._lockfree_enabled
            else "scalar_baseline",
        }

        if self._simd_calculator:
            info.update(self._simd_calculator.get_performance_info())

        if self._concurrent_search:
            info.update(self._concurrent_search.get_performance_info())

        return info
