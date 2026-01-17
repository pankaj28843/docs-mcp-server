"""Tests for segment-based search index implementation."""

import builtins
import importlib
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import patch

import pytest

from docs_mcp_server.domain.search import SearchResponse
from docs_mcp_server.search.bloom_filter import BloomFilter, bloom_positions
import docs_mcp_server.search.segment_search_index as module_under_test
from docs_mcp_server.search.segment_search_index import SegmentSearchIndex
from docs_mcp_server.search.sqlite_storage import _bloom_blocks_from_bits


def _insert_bloom_metadata(conn: sqlite3.Connection, terms: set[str]) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bloom_blocks (
            block_index INTEGER PRIMARY KEY,
            bits INTEGER NOT NULL
        )
    """)

    if not terms:
        metadata = [
            ("bloom_field", "body"),
            ("bloom_bit_size", "0"),
            ("bloom_hash_count", "0"),
            ("bloom_block_bits", "64"),
            ("bloom_item_count", "0"),
        ]
        conn.executemany("INSERT INTO metadata (key, value) VALUES (?, ?)", metadata)
        return

    bloom = BloomFilter(expected_items=len(terms), false_positive_rate=0.01)
    for term in terms:
        bloom.add(term.lower())

    blocks = _bloom_blocks_from_bits(bytes(bloom.bit_array), block_bits=64)
    conn.executemany("INSERT INTO bloom_blocks (block_index, bits) VALUES (?, ?)", blocks)
    metadata = [
        ("bloom_field", "body"),
        ("bloom_bit_size", str(bloom.bit_size)),
        ("bloom_hash_count", str(bloom.hash_count)),
        ("bloom_block_bits", "64"),
        ("bloom_item_count", str(bloom.item_count)),
    ]
    conn.executemany("INSERT INTO metadata (key, value) VALUES (?, ?)", metadata)


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
                info = index.get_performance_info()
                assert info["total_documents"] >= 0
                assert info["avg_document_length"] > 0

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
                assert cursor.fetchone()[0] == 1  # FILE

    def test_init_with_unavailable_optimizations(self):
        """Test initialization when optimizations are requested but unavailable."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            # Mock the availability flags to simulate unavailable optimizations
            with (
                patch("docs_mcp_server.search.segment_search_index.SIMD_AVAILABLE", False),
                patch("docs_mcp_server.search.segment_search_index.LOCKFREE_AVAILABLE", False),
            ):
                with SegmentSearchIndex(
                    db_path, enable_simd=True, enable_lockfree=True, enable_bloom_filter=True
                ) as index:
                    # All optimizations should be disabled due to unavailability
                    assert not index._simd_enabled
                    assert not index._lockfree_enabled
                    assert index._simd_calculator is None
                    assert index._concurrent_search is None

    def _create_test_database(self, db_path: Path):
        """Create a test database with required schema."""
        with sqlite3.connect(db_path) as conn:
            # Create documents table
            conn.execute("""
                CREATE TABLE documents (
                    doc_id TEXT PRIMARY KEY,
                    url TEXT,
                    url_path TEXT,
                    title TEXT,
                    headings_h1 TEXT,
                    headings_h2 TEXT,
                    headings TEXT,
                    body TEXT,
                    path TEXT,
                    tags TEXT,
                    excerpt TEXT,
                    language TEXT,
                    timestamp TEXT,
                    url_path_length INTEGER,
                    title_length INTEGER,
                    headings_h1_length INTEGER,
                    headings_h2_length INTEGER,
                    headings_length INTEGER,
                    body_length INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # Create postings table
            conn.execute("""
                CREATE TABLE postings (
                    field TEXT,
                    term TEXT,
                    doc_id TEXT,
                    tf INTEGER DEFAULT 1,
                    doc_length INTEGER,
                    positions_blob BLOB
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

            doc_lengths = {}
            for doc_id, doc_data in test_docs:
                body_length = len(doc_data["body"].split())
                doc_lengths[doc_id] = body_length
                conn.execute(
                    "INSERT INTO documents (doc_id, url, title, body, body_length) VALUES (?, ?, ?, ?, ?)",
                    (doc_id, doc_data["url"], doc_data["title"], doc_data["body"], body_length),
                )
            total_terms = sum(doc_lengths.values())
            conn.executemany(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                [("doc_count", str(len(doc_lengths))), ("body_total_terms", str(total_terms))],
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
                    "INSERT INTO postings (field, term, doc_id, tf, doc_length, positions_blob) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (field, term, doc_id, tf, doc_lengths.get(doc_id, 0), None),
                )

            _insert_bloom_metadata(conn, {term for _field, term, _doc_id, _tf in postings_data})
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

    def test_filter_tokens_with_bloom(self):
        """Test bloom filter removes terms not present in the filter."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            with sqlite3.connect(db_path) as conn:
                conn.execute("""
                    CREATE TABLE documents (
                        doc_id TEXT PRIMARY KEY,
                        url TEXT,
                        url_path TEXT,
                        title TEXT,
                        headings_h1 TEXT,
                        headings_h2 TEXT,
                        headings TEXT,
                        body TEXT,
                        path TEXT,
                        tags TEXT,
                        excerpt TEXT,
                        language TEXT,
                        timestamp TEXT,
                        url_path_length INTEGER,
                        title_length INTEGER,
                        headings_h1_length INTEGER,
                        headings_h2_length INTEGER,
                        headings_length INTEGER,
                        body_length INTEGER
                    )
                """)
                conn.execute("""
                    CREATE TABLE metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE postings (
                        field TEXT,
                        term TEXT,
                        doc_id TEXT,
                        tf INTEGER DEFAULT 1,
                        doc_length INTEGER,
                        positions_blob BLOB
                    )
                """)
                conn.execute("""
                    CREATE TABLE bloom_blocks (
                        block_index INTEGER PRIMARY KEY,
                        bits INTEGER NOT NULL
                    )
                """)

                bit_size = 256
                hash_count = 2
                block_bits = 64
                include_term = "alpha"
                include_positions = bloom_positions(include_term, bit_size, hash_count)
                exclude_term = None
                for candidate in ["omega", "delta", "kappa", "theta", "gamma"]:
                    candidate_positions = bloom_positions(candidate, bit_size, hash_count)
                    if set(include_positions).isdisjoint(candidate_positions):
                        exclude_term = candidate
                        exclude_positions = candidate_positions
                        break
                assert exclude_term is not None

                bit_array = bytearray((bit_size + 7) // 8)
                for position in include_positions:
                    byte_index = position // 8
                    bit_offset = position % 8
                    bit_array[byte_index] |= 1 << bit_offset

                blocks = _bloom_blocks_from_bits(bytes(bit_array), block_bits=block_bits)
                conn.executemany(
                    "INSERT INTO bloom_blocks (block_index, bits) VALUES (?, ?)",
                    blocks,
                )
                metadata = [
                    ("bloom_bit_size", str(bit_size)),
                    ("bloom_hash_count", str(hash_count)),
                    ("bloom_block_bits", str(block_bits)),
                ]
                conn.executemany("INSERT INTO metadata (key, value) VALUES (?, ?)", metadata)
                conn.commit()

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                filtered = index._filter_tokens_with_bloom([include_term, exclude_term])

            assert include_term in filtered
            assert exclude_term not in filtered

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

    def _create_test_database(self, db_path: Path):
        """Create a test database with required schema."""
        with sqlite3.connect(db_path) as conn:
            # Create documents table
            conn.execute("""
                CREATE TABLE documents (
                    doc_id TEXT PRIMARY KEY,
                    url TEXT,
                    url_path TEXT,
                    title TEXT,
                    headings_h1 TEXT,
                    headings_h2 TEXT,
                    headings TEXT,
                    body TEXT,
                    path TEXT,
                    tags TEXT,
                    excerpt TEXT,
                    language TEXT,
                    timestamp TEXT,
                    url_path_length INTEGER,
                    title_length INTEGER,
                    headings_h1_length INTEGER,
                    headings_h2_length INTEGER,
                    headings_length INTEGER,
                    body_length INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # Create postings table
            conn.execute("""
                CREATE TABLE postings (
                    field TEXT,
                    term TEXT,
                    doc_id TEXT,
                    tf INTEGER DEFAULT 1,
                    doc_length INTEGER,
                    positions_blob BLOB
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

            doc_lengths = {}
            for doc_id, doc_data in test_docs:
                body_length = len(doc_data["body"].split())
                doc_lengths[doc_id] = body_length
                conn.execute(
                    "INSERT INTO documents (doc_id, url, title, body, body_length) VALUES (?, ?, ?, ?, ?)",
                    (doc_id, doc_data["url"], doc_data["title"], doc_data["body"], body_length),
                )
            total_terms = sum(doc_lengths.values())
            conn.executemany(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                [("doc_count", str(len(doc_lengths))), ("body_total_terms", str(total_terms))],
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
                    "INSERT INTO postings (field, term, doc_id, tf, doc_length, positions_blob) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (field, term, doc_id, tf, doc_lengths.get(doc_id, 0), None),
                )

            _insert_bloom_metadata(conn, {term for _field, term, _doc_id, _tf in postings_data})
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
                total_docs, avg_doc_length = index._get_corpus_stats()
                scores = index._calculate_bm25_scores_scalar(tokens, total_docs, avg_doc_length)

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
                total_docs, avg_doc_length = index._get_corpus_stats()
                scores = index._calculate_bm25_scores_scalar([], total_docs, avg_doc_length)

                assert isinstance(scores, dict)
                assert len(scores) == 0

    def test_calculate_bm25_scores_nonexistent_terms(self):
        """Test BM25 calculation with terms not in index."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            self._create_test_database(db_path)

            with SegmentSearchIndex(db_path, enable_simd=False, enable_lockfree=False) as index:
                total_docs, avg_doc_length = index._get_corpus_stats()
                scores = index._calculate_bm25_scores_scalar(["nonexistent", "missing"], total_docs, avg_doc_length)

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
                        with patch.object(
                            index._simd_calculator, "calculate_scores_vectorized", return_value=[1.0, 2.0]
                        ):
                            scores = index._calculate_bm25_scores(["test", "document"])
                            assert isinstance(scores, dict)

    def _create_test_database(self, db_path: Path):
        """Create a test database with required schema."""
        with sqlite3.connect(db_path) as conn:
            # Create documents table
            conn.execute("""
                CREATE TABLE documents (
                    doc_id TEXT PRIMARY KEY,
                    url TEXT,
                    url_path TEXT,
                    title TEXT,
                    headings_h1 TEXT,
                    headings_h2 TEXT,
                    headings TEXT,
                    body TEXT,
                    path TEXT,
                    tags TEXT,
                    excerpt TEXT,
                    language TEXT,
                    timestamp TEXT,
                    url_path_length INTEGER,
                    title_length INTEGER,
                    headings_h1_length INTEGER,
                    headings_h2_length INTEGER,
                    headings_length INTEGER,
                    body_length INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # Create postings table
            conn.execute("""
                CREATE TABLE postings (
                    field TEXT,
                    term TEXT,
                    doc_id TEXT,
                    tf INTEGER DEFAULT 1,
                    doc_length INTEGER,
                    positions_blob BLOB
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

            doc_lengths = {}
            for doc_id, doc_data in test_docs:
                body_length = len(doc_data["body"].split())
                doc_lengths[doc_id] = body_length
                conn.execute(
                    "INSERT INTO documents (doc_id, url, title, body, body_length) VALUES (?, ?, ?, ?, ?)",
                    (doc_id, doc_data["url"], doc_data["title"], doc_data["body"], body_length),
                )
            total_terms = sum(doc_lengths.values())
            conn.executemany(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                [("doc_count", str(len(doc_lengths))), ("body_total_terms", str(total_terms))],
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
                    "INSERT INTO postings (field, term, doc_id, tf, doc_length, positions_blob) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (field, term, doc_id, tf, doc_lengths.get(doc_id, 0), None),
                )

            _insert_bloom_metadata(conn, {term for _field, term, _doc_id, _tf in postings_data})
            conn.commit()


class TestSegmentSearchIndexHelpers:
    """Test helper methods."""

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
                    url TEXT,
                    url_path TEXT,
                    title TEXT,
                    headings_h1 TEXT,
                    headings_h2 TEXT,
                    headings TEXT,
                    body TEXT,
                    path TEXT,
                    tags TEXT,
                    excerpt TEXT,
                    language TEXT,
                    timestamp TEXT,
                    url_path_length INTEGER,
                    title_length INTEGER,
                    headings_h1_length INTEGER,
                    headings_h2_length INTEGER,
                    headings_length INTEGER,
                    body_length INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # Create postings table
            conn.execute("""
                CREATE TABLE postings (
                    field TEXT,
                    term TEXT,
                    doc_id TEXT,
                    tf INTEGER DEFAULT 1,
                    doc_length INTEGER,
                    positions_blob BLOB
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

            doc_lengths = {}
            for doc_id, doc_data in test_docs:
                body_length = len(doc_data["body"].split())
                doc_lengths[doc_id] = body_length
                conn.execute(
                    "INSERT INTO documents (doc_id, url, title, body, body_length) VALUES (?, ?, ?, ?, ?)",
                    (doc_id, doc_data["url"], doc_data["title"], doc_data["body"], body_length),
                )
            total_terms = sum(doc_lengths.values())
            conn.executemany(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                [("doc_count", str(len(doc_lengths))), ("body_total_terms", str(total_terms))],
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
                    "INSERT INTO postings (field, term, doc_id, tf, doc_length, positions_blob) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (field, term, doc_id, tf, doc_lengths.get(doc_id, 0), None),
                )

            _insert_bloom_metadata(conn, {term for _field, term, _doc_id, _tf in postings_data})
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
                    url TEXT,
                    url_path TEXT,
                    title TEXT,
                    headings_h1 TEXT,
                    headings_h2 TEXT,
                    headings TEXT,
                    body TEXT,
                    path TEXT,
                    tags TEXT,
                    excerpt TEXT,
                    language TEXT,
                    timestamp TEXT,
                    url_path_length INTEGER,
                    title_length INTEGER,
                    headings_h1_length INTEGER,
                    headings_h2_length INTEGER,
                    headings_length INTEGER,
                    body_length INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # Create postings table
            conn.execute("""
                CREATE TABLE postings (
                    field TEXT,
                    term TEXT,
                    doc_id TEXT,
                    tf INTEGER DEFAULT 1,
                    doc_length INTEGER,
                    positions_blob BLOB
                )
            """)

            # Insert minimal test data
            conn.execute(
                "INSERT INTO documents (doc_id, url, title, body, body_length) VALUES (?, ?, ?, ?, ?)",
                ("doc1", "http://example.com/doc1", "Test", "Test content", 2),
            )
            conn.executemany(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                [("doc_count", "1"), ("body_total_terms", "2")],
            )

            conn.execute(
                "INSERT INTO postings (field, term, doc_id, tf, doc_length, positions_blob) VALUES (?, ?, ?, ?, ?, ?)",
                ("body", "test", "doc1", 1, 2, None),
            )

            _insert_bloom_metadata(conn, {"test"})
            conn.commit()


class TestSegmentSearchIndexEdgeCases:
    """Test edge cases and error handling."""

    def test_missing_tables_graceful_handling(self):
        """Test missing tables raise during search."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            # Create minimal database without all tables
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY)")
                conn.commit()

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                with pytest.raises(sqlite3.OperationalError):
                    index.search("test")

    def test_empty_database(self):
        """Test behavior with empty database."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            with sqlite3.connect(db_path) as conn:
                # Create empty tables
                conn.execute("""
                    CREATE TABLE documents (
                        doc_id TEXT PRIMARY KEY,
                        url TEXT,
                        url_path TEXT,
                        title TEXT,
                        headings_h1 TEXT,
                        headings_h2 TEXT,
                        headings TEXT,
                        body TEXT,
                        path TEXT,
                        tags TEXT,
                        excerpt TEXT,
                        language TEXT,
                        timestamp TEXT,
                        url_path_length INTEGER,
                        title_length INTEGER,
                        headings_h1_length INTEGER,
                        headings_h2_length INTEGER,
                        headings_length INTEGER,
                        body_length INTEGER
                    )
                """)
                conn.execute("""
                    CREATE TABLE metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
                conn.execute(
                    "CREATE TABLE postings (field TEXT, term TEXT, doc_id TEXT, tf INTEGER, doc_length INTEGER, positions_blob BLOB)"
                )
                conn.executemany(
                    "INSERT INTO metadata (key, value) VALUES (?, ?)",
                    [("doc_count", "0"), ("body_total_terms", "0")],
                )
                _insert_bloom_metadata(conn, set())
                conn.commit()

            with SegmentSearchIndex(db_path, enable_lockfree=False) as index:
                response = index.search("any query")
                assert isinstance(response, SearchResponse)
                assert len(response.results) == 0


def test_optional_import_flags_fallback(monkeypatch):
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name in {
            "docs_mcp_server.search.simd_bm25",
            "docs_mcp_server.search.lockfree_concurrent",
        }:
            raise ImportError("boom")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    reloaded = importlib.reload(module_under_test)

    assert reloaded.SIMD_AVAILABLE is False
    assert reloaded.LOCKFREE_AVAILABLE is False
    importlib.reload(module_under_test)


def test_performance_info_includes_concurrent_search(tmp_path):
    db_path = tmp_path / "segments.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE documents (
                doc_id TEXT PRIMARY KEY,
                url TEXT,
                url_path TEXT,
                title TEXT,
                headings_h1 TEXT,
                headings_h2 TEXT,
                headings TEXT,
                body TEXT,
                path TEXT,
                tags TEXT,
                excerpt TEXT,
                language TEXT,
                timestamp TEXT,
                url_path_length INTEGER,
                title_length INTEGER,
                headings_h1_length INTEGER,
                headings_h2_length INTEGER,
                headings_length INTEGER,
                body_length INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.executemany(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            [("doc_count", "0"), ("body_total_terms", "0")],
        )
        _insert_bloom_metadata(conn, set())
        conn.commit()
    index = SegmentSearchIndex(db_path, enable_simd=False, enable_lockfree=False, enable_bloom_filter=False)

    class _Concurrent:
        def get_performance_info(self):
            return {"lockfree": True}

    index._concurrent_search = _Concurrent()

    info = index.get_performance_info()

    assert info["lockfree"] is True
