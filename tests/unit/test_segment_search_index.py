"""Tests for segment-based search index implementation."""

import json
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import patch

from docs_mcp_server.domain.search import SearchResponse
from docs_mcp_server.search.segment_search_index import SegmentSearchIndex


class TestSegmentSearchIndexInit:
    """Test SegmentSearchIndex initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default optimization settings."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path) as index:
                assert index.db_path == db_path
                assert index._conn is not None
                assert index._total_docs >= 0
                assert index._avg_doc_length > 0

    def test_init_with_disabled_optimizations(self):
        """Test initialization with all optimizations disabled."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(
                db_path, enable_simd=False, enable_lockfree=False, enable_bloom_filter=False
            ) as index:
                assert index._simd_enabled is False
                assert index._lockfree_enabled is False
                assert index._bloom_filter_enabled is False

    def test_context_manager_lifecycle(self):
        """Test context manager properly manages resources."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path) as index:
                assert isinstance(index, SegmentSearchIndex)
                assert index._conn is not None

            # After context exit, connection should be closed
            assert index._conn is None

    def test_init_creates_optimized_connection(self):
        """Test initialization creates properly optimized SQLite connection."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                # Test some PRAGMA settings
                cursor = index._conn.execute("PRAGMA journal_mode")
                assert cursor.fetchone()[0] == "wal"

                cursor = index._conn.execute("PRAGMA synchronous")
                assert cursor.fetchone()[0] == 1  # NORMAL

                cursor = index._conn.execute("PRAGMA temp_store")
                assert cursor.fetchone()[0] == 2  # MEMORY

    def test_init_with_unavailable_optimizations(self):
        """Test initialization when optimizations are requested but unavailable."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            # Mock the availability flags to simulate unavailable optimizations
            with patch("docs_mcp_server.search.segment_search_index.SIMD_AVAILABLE", False), \
                 patch("docs_mcp_server.search.segment_search_index.LOCKFREE_AVAILABLE", False), \
                 patch("docs_mcp_server.search.segment_search_index.BLOOM_FILTER_AVAILABLE", False):
                
                with SegmentSearchIndex(
                    db_path, enable_simd=True, enable_lockfree=True, enable_bloom_filter=True
                ) as index:
                    # All optimizations should be disabled due to unavailability
                    assert not index._simd_enabled
                    assert not index._lockfree_enabled
                    assert not index._bloom_filter_enabled
                    assert index._simd_calculator is None
                    assert index._concurrent_search is None
                    assert index._bloom_optimizer is None

    def _create_test_database(self, db_path: Path):
        """Create a test database with required schema."""
        with sqlite3.connect(db_path) as conn:
            # Create documents table
            conn.execute("""
                CREATE TABLE documents (
                    doc_id TEXT PRIMARY KEY,
                    field_data TEXT
                )
            """)

            # Create postings table
            conn.execute("""
                CREATE TABLE postings (
                    field TEXT,
                    term TEXT,
                    doc_id TEXT,
                    tf INTEGER DEFAULT 1
                )
            """)

            # Create field_lengths table
            conn.execute("""
                CREATE TABLE field_lengths (
                    doc_id TEXT,
                    field TEXT,
                    length INTEGER
                )
            """)

            # Insert test data
            test_docs = [
                (
                    "doc1",
                    {
                        "url": "http://example.com/doc1",
                        "title": "Test Document 1",
                        "body": "This is a test document about Python programming.",
                    },
                ),
                (
                    "doc2",
                    {
                        "url": "http://example.com/doc2",
                        "title": "Test Document 2",
                        "body": "Another test document discussing web development and JavaScript.",
                    },
                ),
                (
                    "doc3",
                    {
                        "url": "http://example.com/doc3",
                        "title": "Test Document 3",
                        "body": "A third document covering database design and SQL queries.",
                    },
                ),
            ]

            for doc_id, doc_data in test_docs:
                conn.execute("INSERT INTO documents (doc_id, field_data) VALUES (?, ?)", (doc_id, json.dumps(doc_data)))

                # Add field lengths
                body_length = len(doc_data["body"].split())
                conn.execute(
                    "INSERT INTO field_lengths (doc_id, field, length) VALUES (?, ?, ?)", (doc_id, "body", body_length)
                )

            # Insert postings data
            postings_data = [
                ("body", "test", "doc1", 2),
                ("body", "test", "doc2", 1),
                ("body", "test", "doc3", 1),
                ("body", "document", "doc1", 1),
                ("body", "document", "doc2", 1),
                ("body", "document", "doc3", 1),
                ("body", "python", "doc1", 1),
                ("body", "programming", "doc1", 1),
                ("body", "web", "doc2", 1),
                ("body", "development", "doc2", 1),
                ("body", "javascript", "doc2", 1),
                ("body", "database", "doc3", 1),
                ("body", "design", "doc3", 1),
                ("body", "sql", "doc3", 1),
                ("body", "queries", "doc3", 1),
            ]

            for field, term, doc_id, tf in postings_data:
                conn.execute(
                    "INSERT INTO postings (field, term, doc_id, tf) VALUES (?, ?, ?, ?)", (field, term, doc_id, tf)
                )

            conn.commit()


class TestSegmentSearchIndexSearch:
    """Test search functionality."""

    def test_search_basic_query(self):
        """Test basic search functionality."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                response = index.search("test document")

                assert isinstance(response, SearchResponse)
                assert len(response.results) > 0

                # All results should have valid scores (can be negative for common terms)
                for result in response.results:
                    assert isinstance(result.relevance_score, float)
                    assert result.document_url.startswith("http://example.com/")
                    assert "Test Document" in result.document_title

    def test_search_empty_query(self):
        """Test search with empty query."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                response = index.search("")

                assert isinstance(response, SearchResponse)
                assert len(response.results) == 0

    def test_search_no_matches(self):
        """Test search with query that has no matches."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                response = index.search("nonexistent term")

                assert isinstance(response, SearchResponse)
                assert len(response.results) == 0

    def test_search_max_results_limit(self):
        """Test search respects max_results parameter."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                response = index.search("document", max_results=2)

                assert isinstance(response, SearchResponse)
                assert len(response.results) <= 2

    def test_search_scoring_order(self):
        """Test search results are ordered by relevance score."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                response = index.search("test")

                if len(response.results) > 1:
                    # Results should be ordered by score (descending)
                    scores = [result.relevance_score for result in response.results]
                    assert scores == sorted(scores, reverse=True)

    def test_search_with_bloom_filter_optimization(self):
        """Test search with bloom filter optimization enabled."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            # Mock bloom filter to return empty results to test early termination
            with patch("docs_mcp_server.search.segment_search_index.BLOOM_FILTER_AVAILABLE", True):
                with SegmentSearchIndex(db_path, enable_bloom_filter=True) as index:
                    # Mock the bloom optimizer to filter out all terms
                    if index._bloom_optimizer:
                        with patch.object(index._bloom_optimizer, 'filter_query_terms', return_value=[]):
                            response = index.search("test document")
                            assert isinstance(response, SearchResponse)
                            assert len(response.results) == 0  # Should be empty due to bloom filter

    def _create_test_database(self, db_path: Path):
        """Create a test database with required schema."""
        with sqlite3.connect(db_path) as conn:
            # Create documents table
            conn.execute("""
                CREATE TABLE documents (
                    doc_id TEXT PRIMARY KEY,
                    field_data TEXT
                )
            """)

            # Create postings table
            conn.execute("""
                CREATE TABLE postings (
                    field TEXT,
                    term TEXT,
                    doc_id TEXT,
                    tf INTEGER DEFAULT 1
                )
            """)

            # Create field_lengths table
            conn.execute("""
                CREATE TABLE field_lengths (
                    doc_id TEXT,
                    field TEXT,
                    length INTEGER
                )
            """)

            # Insert test data
            test_docs = [
                (
                    "doc1",
                    {
                        "url": "http://example.com/doc1",
                        "title": "Test Document 1",
                        "body": "This is a test document about Python programming.",
                    },
                ),
                (
                    "doc2",
                    {
                        "url": "http://example.com/doc2",
                        "title": "Test Document 2",
                        "body": "Another test document discussing web development and JavaScript.",
                    },
                ),
                (
                    "doc3",
                    {
                        "url": "http://example.com/doc3",
                        "title": "Test Document 3",
                        "body": "A third document covering database design and SQL queries.",
                    },
                ),
            ]

            for doc_id, doc_data in test_docs:
                conn.execute("INSERT INTO documents (doc_id, field_data) VALUES (?, ?)", (doc_id, json.dumps(doc_data)))

                # Add field lengths
                body_length = len(doc_data["body"].split())
                conn.execute(
                    "INSERT INTO field_lengths (doc_id, field, length) VALUES (?, ?, ?)", (doc_id, "body", body_length)
                )

            # Insert postings data
            postings_data = [
                ("body", "test", "doc1", 2),
                ("body", "test", "doc2", 1),
                ("body", "test", "doc3", 1),
                ("body", "document", "doc1", 1),
                ("body", "document", "doc2", 1),
                ("body", "document", "doc3", 1),
                ("body", "python", "doc1", 1),
                ("body", "programming", "doc1", 1),
                ("body", "web", "doc2", 1),
                ("body", "development", "doc2", 1),
                ("body", "javascript", "doc2", 1),
                ("body", "database", "doc3", 1),
                ("body", "design", "doc3", 1),
                ("body", "sql", "doc3", 1),
                ("body", "queries", "doc3", 1),
            ]

            for field, term, doc_id, tf in postings_data:
                conn.execute(
                    "INSERT INTO postings (field, term, doc_id, tf) VALUES (?, ?, ?, ?)", (field, term, doc_id, tf)
                )

            conn.commit()


class TestSegmentSearchIndexBM25:
    """Test BM25 scoring functionality."""

    def test_calculate_bm25_scores_scalar(self):
        """Test scalar BM25 calculation."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_simd=False, enable_lockfree=False) as index:
                tokens = ["test", "document"]
                scores = index._calculate_bm25_scores_scalar(tokens)

                assert isinstance(scores, dict)
                assert len(scores) > 0

                # Scores can be negative in BM25 when terms are very common
                for doc_id, score in scores.items():
                    assert isinstance(score, float)
                    assert isinstance(doc_id, str)

    def test_calculate_bm25_scores_empty_tokens(self):
        """Test BM25 calculation with empty tokens."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_simd=False, enable_lockfree=False) as index:
                scores = index._calculate_bm25_scores_scalar([])

                assert isinstance(scores, dict)
                assert len(scores) == 0

    def test_calculate_bm25_scores_nonexistent_terms(self):
        """Test BM25 calculation with terms not in index."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_simd=False, enable_lockfree=False) as index:
                scores = index._calculate_bm25_scores_scalar(["nonexistent", "missing"])

                assert isinstance(scores, dict)
                assert len(scores) == 0

    def test_calculate_bm25_scores_with_simd(self):
        """Test BM25 calculation with SIMD optimization enabled."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            # Mock SIMD availability and test the SIMD path
            with patch("docs_mcp_server.search.segment_search_index.SIMD_AVAILABLE", True):
                with SegmentSearchIndex(db_path, enable_simd=True, enable_lockfree=False) as index:
                    # Mock the SIMD calculator
                    if index._simd_calculator:
                        with patch.object(index._simd_calculator, 'calculate_scores_vectorized', return_value=[1.0, 2.0]):
                            scores = index._calculate_bm25_scores(["test", "document"])
                            assert isinstance(scores, dict)

    def _create_test_database(self, db_path: Path):
        """Create a test database with required schema."""
        with sqlite3.connect(db_path) as conn:
            # Create documents table
            conn.execute("""
                CREATE TABLE documents (
                    doc_id TEXT PRIMARY KEY,
                    field_data TEXT
                )
            """)

            # Create postings table
            conn.execute("""
                CREATE TABLE postings (
                    field TEXT,
                    term TEXT,
                    doc_id TEXT,
                    tf INTEGER DEFAULT 1
                )
            """)

            # Create field_lengths table
            conn.execute("""
                CREATE TABLE field_lengths (
                    doc_id TEXT,
                    field TEXT,
                    length INTEGER
                )
            """)

            # Insert test data
            test_docs = [
                (
                    "doc1",
                    {
                        "url": "http://example.com/doc1",
                        "title": "Test Document 1",
                        "body": "This is a test document about Python programming.",
                    },
                ),
                (
                    "doc2",
                    {
                        "url": "http://example.com/doc2",
                        "title": "Test Document 2",
                        "body": "Another test document discussing web development and JavaScript.",
                    },
                ),
            ]

            for doc_id, doc_data in test_docs:
                conn.execute("INSERT INTO documents (doc_id, field_data) VALUES (?, ?)", (doc_id, json.dumps(doc_data)))

                # Add field lengths
                body_length = len(doc_data["body"].split())
                conn.execute(
                    "INSERT INTO field_lengths (doc_id, field, length) VALUES (?, ?, ?)", (doc_id, "body", body_length)
                )

            # Insert postings data
            postings_data = [
                ("body", "test", "doc1", 2),
                ("body", "test", "doc2", 1),
                ("body", "document", "doc1", 1),
                ("body", "document", "doc2", 1),
                ("body", "python", "doc1", 1),
                ("body", "programming", "doc1", 1),
            ]

            for field, term, doc_id, tf in postings_data:
                conn.execute(
                    "INSERT INTO postings (field, term, doc_id, tf) VALUES (?, ?, ?, ?)", (field, term, doc_id, tf)
                )

            conn.commit()


class TestSegmentSearchIndexHelpers:
    """Test helper methods."""

    def test_get_document_length(self):
        """Test document length retrieval."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                length = index._get_document_length("doc1")
                assert length > 0
                assert isinstance(length, float)

    def test_get_document_length_missing_doc(self):
        """Test document length for missing document."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                length = index._get_document_length("nonexistent")
                assert length == index._avg_doc_length

    def test_get_document_data(self):
        """Test document data retrieval."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                data = index._get_document_data("doc1")

                assert isinstance(data, dict)
                assert "url" in data
                assert "title" in data
                assert "body" in data

    def test_get_document_data_missing_doc(self):
        """Test document data for missing document."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                data = index._get_document_data("nonexistent")
                assert data is None

    def test_get_total_document_count(self):
        """Test total document count."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                count = index._get_total_document_count()
                assert count >= 0
                assert isinstance(count, int)

    def test_get_average_document_length(self):
        """Test average document length calculation."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                avg_length = index._get_average_document_length()
                assert avg_length > 0
                assert isinstance(avg_length, float)

    def _create_test_database(self, db_path: Path):
        """Create a test database with required schema."""
        with sqlite3.connect(db_path) as conn:
            # Create documents table
            conn.execute("""
                CREATE TABLE documents (
                    doc_id TEXT PRIMARY KEY,
                    field_data TEXT
                )
            """)

            # Create postings table
            conn.execute("""
                CREATE TABLE postings (
                    field TEXT,
                    term TEXT,
                    doc_id TEXT,
                    tf INTEGER DEFAULT 1
                )
            """)

            # Create field_lengths table
            conn.execute("""
                CREATE TABLE field_lengths (
                    doc_id TEXT,
                    field TEXT,
                    length INTEGER
                )
            """)

            # Insert test data
            test_docs = [
                (
                    "doc1",
                    {
                        "url": "http://example.com/doc1",
                        "title": "Test Document 1",
                        "body": "This is a test document about Python programming.",
                    },
                ),
                (
                    "doc2",
                    {
                        "url": "http://example.com/doc2",
                        "title": "Test Document 2",
                        "body": "Another test document discussing web development and JavaScript.",
                    },
                ),
            ]

            for doc_id, doc_data in test_docs:
                conn.execute("INSERT INTO documents (doc_id, field_data) VALUES (?, ?)", (doc_id, json.dumps(doc_data)))

                # Add field lengths
                body_length = len(doc_data["body"].split())
                conn.execute(
                    "INSERT INTO field_lengths (doc_id, field, length) VALUES (?, ?, ?)", (doc_id, "body", body_length)
                )

            # Insert postings data
            postings_data = [
                ("body", "test", "doc1", 2),
                ("body", "test", "doc2", 1),
                ("body", "document", "doc1", 1),
                ("body", "document", "doc2", 1),
            ]

            for field, term, doc_id, tf in postings_data:
                conn.execute(
                    "INSERT INTO postings (field, term, doc_id, tf) VALUES (?, ?, ?, ?)", (field, term, doc_id, tf)
                )

            conn.commit()


class TestSegmentSearchIndexOptimizations:
    """Test optimization features."""

    def test_get_performance_info_basic(self):
        """Test performance info retrieval."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                info = index.get_performance_info()

                assert isinstance(info, dict)
                assert "total_documents" in info
                assert "avg_document_length" in info
                assert "simd_enabled" in info
                assert "lockfree_enabled" in info
                assert "bloom_filter_enabled" in info
                assert "optimization_level" in info

    def test_optimization_flags_respected(self):
        """Test optimization flags are respected."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(
                db_path, enable_simd=False, enable_lockfree=False, enable_bloom_filter=False
            ) as index:
                info = index.get_performance_info()

                assert info["simd_enabled"] is False
                assert info["lockfree_enabled"] is False
                assert info["bloom_filter_enabled"] is False

    def test_execute_query_methods(self):
        """Test query execution methods."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                # Test _execute_query
                results = index._execute_query("SELECT COUNT(*) FROM documents")
                assert len(results) == 1
                assert results[0][0] >= 0

                # Test _execute_single_query
                result = index._execute_single_query("SELECT COUNT(*) FROM documents")
                assert result is not None
                assert result[0] >= 0

    def test_close_method(self):
        """Test close method properly cleans up resources."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            index = SegmentSearchIndex(db_path, enable_lockfree=False)
            assert index._conn is not None

            index.close()
            assert index._conn is None

    def _create_test_database(self, db_path: Path):
        """Create a test database with required schema."""
        with sqlite3.connect(db_path) as conn:
            # Create documents table
            conn.execute("""
                CREATE TABLE documents (
                    doc_id TEXT PRIMARY KEY,
                    field_data TEXT
                )
            """)

            # Create postings table
            conn.execute("""
                CREATE TABLE postings (
                    field TEXT,
                    term TEXT,
                    doc_id TEXT,
                    tf INTEGER DEFAULT 1
                )
            """)

            # Create field_lengths table
            conn.execute("""
                CREATE TABLE field_lengths (
                    doc_id TEXT,
                    field TEXT,
                    length INTEGER
                )
            """)

            # Insert minimal test data
            conn.execute(
                "INSERT INTO documents (doc_id, field_data) VALUES (?, ?)",
                ("doc1", json.dumps({"url": "http://example.com/doc1", "title": "Test", "body": "Test content"})),
            )

            conn.execute("INSERT INTO field_lengths (doc_id, field, length) VALUES (?, ?, ?)", ("doc1", "body", 2))

            conn.execute(
                "INSERT INTO postings (field, term, doc_id, tf) VALUES (?, ?, ?, ?)", ("body", "test", "doc1", 1)
            )

            conn.commit()


class TestSegmentSearchIndexEdgeCases:
    """Test edge cases and error handling."""

    def test_malformed_document_data(self):
        """Test handling of malformed document data."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            with sqlite3.connect(db_path) as conn:
                # Create schema
                conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, field_data TEXT)")

                # Insert malformed JSON
                conn.execute("INSERT INTO documents (doc_id, field_data) VALUES (?, ?)", ("doc1", "invalid json"))
                conn.commit()

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                data = index._get_document_data("doc1")
                assert data is None

    def test_missing_tables_graceful_handling(self):
        """Test graceful handling of missing database tables."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            # Create minimal database without all tables
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, field_data TEXT)")
                conn.commit()

            # Should not crash during initialization
            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                assert index._total_docs == 0
                assert index._avg_doc_length == 1000.0  # Default fallback

    def test_empty_database(self):
        """Test behavior with empty database."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            with sqlite3.connect(db_path) as conn:
                # Create empty tables
                conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, field_data TEXT)")
                conn.execute("CREATE TABLE postings (field TEXT, term TEXT, doc_id TEXT, tf INTEGER)")
                conn.execute("CREATE TABLE field_lengths (doc_id TEXT, field TEXT, length INTEGER)")
                conn.commit()

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                response = index.search("any query")
                assert isinstance(response, SearchResponse)
                assert len(response.results) == 0

    def test_postings_table_without_tf_column(self):
        """Test fallback when postings table doesn't have tf column."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            with sqlite3.connect(db_path) as conn:
                # Create tables without tf column in postings
                conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, field_data TEXT)")
                conn.execute("CREATE TABLE postings (field TEXT, term TEXT, doc_id TEXT)")
                conn.execute("CREATE TABLE field_lengths (doc_id TEXT, field TEXT, length INTEGER)")

                # Insert test data
                conn.execute(
                    "INSERT INTO documents (doc_id, field_data) VALUES (?, ?)",
                    ("doc1", json.dumps({"url": "http://example.com/doc1", "title": "Test", "body": "Test content"})),
                )
                conn.execute("INSERT INTO postings (field, term, doc_id) VALUES (?, ?, ?)", ("body", "test", "doc1"))
                conn.execute("INSERT INTO field_lengths (doc_id, field, length) VALUES (?, ?, ?)", ("doc1", "body", 2))
                conn.commit()

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                # Should use fallback tf=1 for all terms
                scores = index._calculate_bm25_scores_scalar(["test"])
                assert len(scores) > 0
                assert "doc1" in scores
