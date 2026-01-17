"""SQLite-based storage engine for high-performance search indexing.

Optimized SQLite backend following best practices from SQLite documentation:
- WAL mode with NORMAL synchronous for performance
- Memory-mapped I/O and optimized cache settings
- WITHOUT ROWID tables for clustered indexes
- Binary position encoding for memory efficiency
- Connection pooling with prepared statements
"""

from __future__ import annotations

from array import array
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any
from uuid import uuid4

from docs_mcp_server.search.analyzers import KeywordAnalyzer, get_analyzer
from docs_mcp_server.search.bloom_filter import BloomFilter
from docs_mcp_server.search.models import Posting
from docs_mcp_server.search.schema import KeywordField, NumericField, Schema, TextField
from docs_mcp_server.search.sqlite_pragmas import apply_read_pragmas, apply_write_pragmas
from docs_mcp_server.search.stats import FieldLengthStats


logger = logging.getLogger(__name__)

_DOCUMENT_COLUMNS = (
    "url",
    "url_path",
    "title",
    "headings_h1",
    "headings_h2",
    "headings",
    "body",
    "path",
    "tags",
    "excerpt",
    "language",
    "timestamp",
)

_LENGTH_COLUMN_BY_FIELD = {
    "url_path": "url_path_length",
    "title": "title_length",
    "headings_h1": "headings_h1_length",
    "headings_h2": "headings_h2_length",
    "headings": "headings_length",
    "body": "body_length",
}

_LENGTH_QUERY_BY_FIELD = {
    field_name: f"SELECT COUNT(*), SUM({length_column}) FROM documents"
    for field_name, length_column in _LENGTH_COLUMN_BY_FIELD.items()
}

_BLOOM_FALSE_POSITIVE_RATE = 0.01
_BLOOM_BLOCK_BITS = 64
_BLOOM_FIELD = "body"


def _document_select_clause(*, with_doc_id: bool) -> str:
    columns = ("doc_id", *_DOCUMENT_COLUMNS) if with_doc_id else _DOCUMENT_COLUMNS
    return f"SELECT {', '.join(columns)} FROM documents"


def _document_row_to_dict(row: sqlite3.Row | tuple, *, with_doc_id: bool) -> dict[str, Any]:
    offset = 1 if with_doc_id else 0
    values = row[offset:]
    document = dict(zip(_DOCUMENT_COLUMNS, values, strict=False))
    return {key: value for key, value in document.items() if value not in (None, "")}


def _bloom_blocks_from_bits(bit_array: bytes, *, block_bits: int) -> list[tuple[int, int]]:
    block_bytes = block_bits // 8
    if block_bytes <= 0 or block_bits % 8 != 0:
        raise ValueError("Bloom block size must be a positive multiple of 8 bits")
    if not bit_array:
        return []
    padded = bit_array
    pad_len = (-len(padded)) % block_bytes
    if pad_len:
        padded += b"\x00" * pad_len
    blocks: list[tuple[int, int]] = []
    for offset in range(0, len(padded), block_bytes):
        chunk = padded[offset : offset + block_bytes]
        block_value = int.from_bytes(chunk, byteorder="little", signed=True)
        blocks.append((offset // block_bytes, block_value))
    return blocks


def _validate_bloom_block_bits() -> None:
    if _BLOOM_BLOCK_BITS <= 0 or _BLOOM_BLOCK_BITS % 8 != 0:
        raise RuntimeError(f"Invalid bloom block size {_BLOOM_BLOCK_BITS}; must be a positive multiple of 8 bits")


class SQLiteConnectionPool:
    """Thread-safe connection pool with thread-local connections."""

    def __init__(self, db_path: Path, max_connections: int = 5):
        self.db_path = db_path
        self.max_connections = max_connections
        self._local = threading.local()

    @contextmanager
    def get_connection(self):
        """Get a thread-local connection."""
        if not hasattr(self._local, "connection") or self._local.connection is None:
            self._local.connection = self._create_connection()

        yield self._local.connection

    def _create_connection(self) -> sqlite3.Connection:
        """Create connection with optimal performance settings."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False, cached_statements=0)
        apply_read_pragmas(conn)
        return conn

    def close_all(self) -> None:
        """Close thread-local connection."""
        if hasattr(self._local, "connection") and self._local.connection is not None:
            try:
                self._local.connection.close()
            except sqlite3.Error:
                pass  # Ignore errors during cleanup
            self._local.connection = None


@dataclass(slots=True)
class SqliteSegment:
    """Immutable SQLite segment following value object pattern."""

    schema: Schema
    db_path: Path
    segment_id: str
    created_at: datetime
    doc_count: int
    _pool: SQLiteConnectionPool | None = None

    def __post_init__(self):
        """Initialize connection pool lazily."""
        if self._pool is None:
            object.__setattr__(self, "_pool", SQLiteConnectionPool(self.db_path))

    def get_postings(self, field_name: str, term: str, *, include_positions: bool = False) -> list[Posting]:
        """Get postings for a specific field and term."""
        if include_positions:
            query = "SELECT doc_id, tf, doc_length, positions_blob FROM postings WHERE field = ? AND term = ?"
        else:
            query = "SELECT doc_id, tf, doc_length FROM postings WHERE field = ? AND term = ?"

        with self._pool.get_connection() as conn:
            cursor = conn.execute(query, (field_name, term))
            postings: list[Posting] = []
            for row in cursor:
                doc_id, tf, doc_length = row[:3]
                positions_blob = row[3] if include_positions else None
                positions = array("I")
                if positions_blob:
                    positions.frombytes(positions_blob)
                postings.append(
                    Posting(
                        doc_id=doc_id,
                        frequency=int(tf or 0),
                        positions=positions,
                        doc_length=int(doc_length) if doc_length is not None else None,
                    )
                )
            return postings

    def get_terms(self, field_name: str) -> list[str]:
        """Return distinct terms for a field."""
        with self._pool.get_connection() as conn:
            cursor = conn.execute("SELECT DISTINCT term FROM postings WHERE field = ?", (field_name,))
            return [row[0] for row in cursor if row[0]]

    def get_field_length_stats(self, fields: list[str]) -> dict[str, FieldLengthStats]:
        """Return aggregate length stats for requested fields."""
        stats: dict[str, FieldLengthStats] = {}
        with self._pool.get_connection() as conn:
            for field_name in fields:
                query = _LENGTH_QUERY_BY_FIELD.get(field_name)
                if not query:
                    continue
                row = conn.execute(query).fetchone()
                if not row:
                    continue
                doc_count, total_terms = row
                stats[field_name] = FieldLengthStats(
                    field=field_name,
                    total_terms=int(total_terms or 0),
                    document_count=int(doc_count or 0),
                )
        return stats

    @property
    def stored_fields(self) -> dict[str, dict[str, Any]]:
        """Get all stored fields."""
        stored_fields = {}
        with self._pool.get_connection() as conn:
            cursor = conn.execute(_document_select_clause(with_doc_id=True))
            for row in cursor:
                doc_id = row[0]
                stored = _document_row_to_dict(row, with_doc_id=True)
                if stored:
                    stored_fields[doc_id] = stored
        return stored_fields

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """Retrieve document using optimized query."""
        with self._pool.get_connection() as conn:
            cursor = conn.execute(_document_select_clause(with_doc_id=False) + " WHERE doc_id = ?", (doc_id,))
            row = cursor.fetchone()
            if not row:
                return None
            stored = _document_row_to_dict(row, with_doc_id=False)
            return stored or None

    def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            self._pool.close_all()


class SqliteSegmentStore:
    """SQLite storage following repository pattern from Cosmic Python."""

    MANIFEST_FILENAME = "manifest.json"
    DB_SUFFIX = ".db"
    DEFAULT_MAX_SEGMENTS = 32
    MAX_SEGMENTS = DEFAULT_MAX_SEGMENTS

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self.directory / self.MANIFEST_FILENAME

    @classmethod
    def set_max_segments(cls, max_segments: int | None) -> None:
        """Configure segment retention policy."""
        if max_segments is None:
            cls.MAX_SEGMENTS = cls.DEFAULT_MAX_SEGMENTS
        else:
            cls.MAX_SEGMENTS = max(1, max_segments)

    def save(self, segment_data: dict[str, Any], *, related_files: list[Path | str] | None = None) -> Path:
        """Save segment with optimized SQLite schema."""
        segment_id = segment_data.get("segment_id") or segment_data.get("i") or uuid4().hex
        db_path = self._db_path(segment_id)

        # If segment already exists, don't overwrite it
        if db_path.exists():
            # Just update manifest and return existing path
            self._update_manifest(segment_id, segment_data)
            return db_path

        conn = None
        try:
            conn = sqlite3.connect(db_path, cached_statements=0)
            self._apply_optimizations(conn)
            self._create_schema(conn)
            self._store_metadata(conn, segment_id, segment_data)
            self._store_postings(conn, segment_data)
            self._store_bloom_filter(conn, segment_data)
            self._store_documents(conn, segment_data)
            conn.execute("PRAGMA optimize")  # Update query planner stats efficiently
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # Keep WAL size bounded after writes
        except sqlite3.Error as e:
            # Clean up partial file on error
            if db_path.exists():
                try:
                    db_path.unlink()
                except OSError as cleanup_error:
                    logger.warning("Failed to remove partial SQLite segment file %s: %s", db_path, cleanup_error)
            raise RuntimeError(f"Failed to save SQLite segment: {e}") from e
        finally:
            if conn:
                try:
                    conn.close()
                except sqlite3.Error as close_error:
                    logger.warning("Failed to close SQLite connection for %s: %s", db_path, close_error)

        # Update manifest to point to latest segment
        self._update_manifest(segment_id, segment_data)

        return db_path

    def _update_manifest(self, segment_id: str, segment_data: dict[str, Any]) -> None:
        """Update manifest.json to point to the latest segment."""
        # Check if segment already exists to preserve timestamp
        existing_created_at = None
        if self._manifest_path.exists():
            try:
                existing_manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
                if existing_manifest.get("latest_segment_id") == segment_id:
                    existing_created_at = existing_manifest.get("created_at")
            except (OSError, json.JSONDecodeError):
                pass  # Ignore errors, will create new manifest

        # Get actual document count from the database
        db_path = self.directory / f"{segment_id}.db"
        doc_count = 0
        if db_path.exists():
            try:
                with sqlite3.connect(db_path) as conn:
                    doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            except sqlite3.Error:
                doc_count = segment_data.get("doc_count", 0)

        manifest_data = {
            "latest_segment_id": segment_id,
            "created_at": existing_created_at or segment_data.get("created_at", datetime.now(timezone.utc).isoformat()),
            "doc_count": doc_count,
        }
        try:
            self._manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
        except OSError as e:
            # Non-fatal error - segment is still saved
            logger.warning("Failed to update manifest: %s", e)

    def _apply_optimizations(self, conn: sqlite3.Connection) -> None:
        """Apply SQLite performance optimizations."""
        apply_write_pragmas(conn)

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        """Create optimized database schema."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS postings (
                field TEXT NOT NULL,
                term TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                tf INTEGER NOT NULL,
                doc_length INTEGER NOT NULL,
                positions_blob BLOB,
                PRIMARY KEY (field, term, doc_id)
            ) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS bloom_blocks (
                block_index INTEGER PRIMARY KEY,
                bits INTEGER NOT NULL
            ) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS documents (
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
            ) WITHOUT ROWID;

            CREATE INDEX IF NOT EXISTS idx_postings_field_term ON postings(field, term);
        """)

    def _store_metadata(self, conn: sqlite3.Connection, segment_id: str, segment_data: dict[str, Any]) -> None:
        """Store segment metadata."""
        # Handle both new and legacy key formats
        schema_data = segment_data.get("schema") or segment_data.get("s", {})
        created_at = segment_data.get("created_at") or segment_data.get("c") or datetime.now(timezone.utc).isoformat()

        # Ensure schema has required url field for compatibility
        if isinstance(schema_data, dict) and "fields" not in schema_data:
            schema_data = {"fields": [{"name": "url", "type": "text", "stored": True}]}

        field_lengths = segment_data.get("field_lengths", {})
        body_lengths = field_lengths.get("body", {})
        total_body_terms = sum(int(length) for length in body_lengths.values())
        doc_count = int(segment_data.get("doc_count", 0))

        metadata = [
            ("segment_id", segment_id),
            ("schema", json.dumps(schema_data)),
            ("created_at", created_at),
            ("doc_count", str(doc_count)),
            ("body_total_terms", str(total_body_terms)),
        ]
        conn.executemany("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", metadata)

    def _store_postings(self, conn: sqlite3.Connection, segment_data: dict[str, Any]) -> None:
        """Store postings with binary encoding."""
        # Handle both new and legacy key formats
        raw_postings = segment_data.get("postings") or segment_data.get("p", {})
        raw_lengths = segment_data.get("field_lengths", {})
        postings_data = []

        for field_name, terms in raw_postings.items():
            field_lengths = raw_lengths.get(field_name, {})
            for term, posting_list in terms.items():
                for posting_dict in posting_list:
                    doc_id = posting_dict.get("doc_id") or posting_dict.get("d", "")
                    positions = posting_dict.get("positions") or posting_dict.get("p", [])

                    # Binary encode positions for memory efficiency
                    positions_array = array("I", (int(pos) for pos in positions))
                    positions_blob = positions_array.tobytes()
                    tf = len(positions_array)
                    doc_length = int(field_lengths.get(doc_id, 0))

                    postings_data.append((field_name, term, doc_id, tf, doc_length, positions_blob))

        if postings_data:
            conn.executemany(
                "INSERT OR REPLACE INTO postings (field, term, doc_id, tf, doc_length, positions_blob) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                postings_data,
            )

    def _store_bloom_filter(self, conn: sqlite3.Connection, segment_data: dict[str, Any]) -> None:
        """Store bloom filter blocks for fast negative term checks."""
        _validate_bloom_block_bits()
        raw_postings = segment_data.get("postings") or segment_data.get("p", {})
        body_terms = raw_postings.get(_BLOOM_FIELD, {})
        term_count = len(body_terms)

        if term_count <= 0:
            metadata = [
                ("bloom_field", _BLOOM_FIELD),
                ("bloom_bit_size", "0"),
                ("bloom_hash_count", "0"),
                ("bloom_block_bits", str(_BLOOM_BLOCK_BITS)),
                ("bloom_item_count", "0"),
            ]
            conn.executemany("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", metadata)
            return

        bloom = BloomFilter(expected_items=term_count, false_positive_rate=_BLOOM_FALSE_POSITIVE_RATE)
        for term in body_terms:
            bloom.add(str(term).lower())

        blocks = _bloom_blocks_from_bits(bytes(bloom.bit_array), block_bits=_BLOOM_BLOCK_BITS)
        if blocks:
            conn.executemany(
                "INSERT OR REPLACE INTO bloom_blocks (block_index, bits) VALUES (?, ?)",
                blocks,
            )

        metadata = [
            ("bloom_field", _BLOOM_FIELD),
            ("bloom_bit_size", str(bloom.bit_size)),
            ("bloom_hash_count", str(bloom.hash_count)),
            ("bloom_block_bits", str(_BLOOM_BLOCK_BITS)),
            ("bloom_item_count", str(bloom.item_count)),
        ]
        conn.executemany("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", metadata)

    def _store_documents(self, conn: sqlite3.Connection, segment_data: dict[str, Any]) -> None:
        """Store document fields."""
        # Handle both new and legacy key formats
        raw_stored = segment_data.get("stored_fields") or segment_data.get("d", {})
        if not raw_stored:
            return

        raw_lengths = segment_data.get("field_lengths", {})
        lengths_by_doc: dict[str, dict[str, int]] = {}
        for field_name, doc_lengths in raw_lengths.items():
            for doc_id, length in doc_lengths.items():
                lengths_by_doc.setdefault(doc_id, {})[field_name] = int(length)

        documents_data = []
        for doc_id, fields in raw_stored.items():
            lengths = lengths_by_doc.get(doc_id, {})
            documents_data.append(
                (
                    doc_id,
                    fields.get("url"),
                    fields.get("url_path"),
                    fields.get("title"),
                    fields.get("headings_h1"),
                    fields.get("headings_h2"),
                    fields.get("headings"),
                    fields.get("body"),
                    fields.get("path"),
                    fields.get("tags"),
                    fields.get("excerpt"),
                    fields.get("language"),
                    fields.get("timestamp"),
                    lengths.get("url_path"),
                    lengths.get("title"),
                    lengths.get("headings_h1"),
                    lengths.get("headings_h2"),
                    lengths.get("headings"),
                    lengths.get("body"),
                )
            )

        conn.executemany(
            "INSERT OR REPLACE INTO documents ("
            "doc_id, url, url_path, title, headings_h1, headings_h2, headings, body, "
            "path, tags, excerpt, language, timestamp, "
            "url_path_length, title_length, headings_h1_length, headings_h2_length, headings_length, body_length"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            documents_data,
        )

    def load(self, segment_id: str) -> SqliteSegment | None:
        """Load segment by ID following null object pattern."""
        db_path = self._db_path(segment_id)
        if not db_path.exists():
            return None

        conn = None
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            metadata = self._load_metadata(conn)

            if not metadata:
                return None

            schema_data = metadata.get("schema", "{}")
            try:
                schema = Schema.from_dict(json.loads(schema_data))
            except (json.JSONDecodeError, ValueError):
                # Handle corrupted schema
                return None

            created_at_str = metadata.get("created_at", datetime.now(timezone.utc).isoformat())
            try:
                created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            except ValueError:
                created_at = datetime.now(timezone.utc)

            doc_count = int(metadata.get("doc_count", 0) or 0)

            return SqliteSegment(
                schema=schema, db_path=db_path, segment_id=segment_id, created_at=created_at, doc_count=doc_count
            )
        except sqlite3.Error:
            return None
        finally:
            if conn:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass

    def _load_metadata(self, conn: sqlite3.Connection) -> dict[str, str]:
        """Load metadata with error handling."""
        try:
            cursor = conn.execute("SELECT key, value FROM metadata")
            return {row["key"]: row["value"] for row in cursor}
        except sqlite3.OperationalError:
            return {}

    def latest(self) -> SqliteSegment | None:
        """Get most recent segment."""
        latest_id = self.latest_segment_id()
        return self.load(latest_id) if latest_id else None

    def latest_segment_id(self) -> str | None:
        """Get ID of most recent segment."""
        db_files = list(self.directory.glob(f"*{self.DB_SUFFIX}"))
        if not db_files:
            return None
        try:
            return max(db_files, key=lambda p: p.stat().st_mtime).stem
        except OSError:
            return None

    def latest_doc_count(self) -> int | None:
        """Get document count of latest segment."""
        latest = self.latest()
        return latest.doc_count if latest else None

    def segment_path(self, segment_id: str) -> Path | None:
        """Get path to segment if it exists."""
        path = self._db_path(segment_id)
        return path if path.exists() else None

    def list_segments(self) -> list[dict[str, Any]]:
        """List all segments with metadata."""
        segments = []
        for db_file in self.directory.glob(f"*{self.DB_SUFFIX}"):
            try:
                segment = self.load(db_file.stem)
                if segment:
                    segments.append(
                        {
                            "segment_id": segment.segment_id,
                            "created_at": segment.created_at.isoformat(),
                            "doc_count": segment.doc_count,
                            "files": [db_file.name],
                        }
                    )
            except Exception:
                # Skip corrupted segments
                continue
        return segments

    def prune_to_segment_ids(self, keep_segment_ids: list[str]) -> None:
        """Remove segments not in keep list."""
        keep_set = set(keep_segment_ids)
        for db_file in self.directory.glob(f"*{self.DB_SUFFIX}"):
            if db_file.stem not in keep_set:
                try:
                    db_file.unlink()
                except OSError:
                    pass  # Ignore errors during cleanup
                for sidecar in db_file.parent.glob(f"{db_file.name}-*"):
                    try:
                        sidecar.unlink()
                    except OSError:
                        pass  # Ignore errors during cleanup
        for sidecar in self.directory.glob(f"*{self.DB_SUFFIX}-*"):
            base_name = sidecar.name.split(f"{self.DB_SUFFIX}-", 1)[0]
            if base_name not in keep_set:
                try:
                    sidecar.unlink()
                except OSError:
                    pass  # Ignore errors during cleanup

    def _db_path(self, segment_id: str) -> Path:
        """Get database path for segment."""
        return self.directory / f"{segment_id}{self.DB_SUFFIX}"


class SqliteSegmentWriter:
    """Builds SQLite segments from schema-aware documents."""

    def __init__(self, schema: Schema, *, segment_id: str | None = None) -> None:
        self.schema = schema
        self.segment_id = segment_id or uuid4().hex
        self.created_at = datetime.now(timezone.utc)
        self._postings = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        self._field_lengths = defaultdict(dict)
        self._stored_fields = {}
        self._keyword_analyzer = KeywordAnalyzer()
        self._allowed_stored_fields = {
            "url",
            "url_path",
            "title",
            "excerpt",
            "body",
            "headings_h1",
            "headings_h2",
            "headings",
            "path",
            "tags",
            "timestamp",
            "language",
        }
        self._allowed_stored_fields.add(self.schema.unique_field)

    def add_document(self, document: dict[str, Any]) -> str:
        """Add document to segment."""

        doc_key = self._normalize_unique(document)
        if doc_key in self._stored_fields:
            raise ValueError(f"Duplicate document for unique field '{self.schema.unique_field}': {doc_key}")

        stored = {}
        for schema_field in self.schema.fields:
            value = document.get(schema_field.name)
            if schema_field.stored and schema_field.name in self._allowed_stored_fields:
                normalized = self._normalize_stored_value(schema_field.name, value)
                if normalized not in (None, ""):
                    stored[schema_field.name] = normalized

            if not schema_field.indexed:
                continue

            tokens = self._analyze_field(schema_field, value)
            if not tokens:
                continue

            self._field_lengths[schema_field.name][doc_key] = len(tokens)
            for token in tokens:
                terms = self._postings[schema_field.name][token.text]
                positions = terms[doc_key]
                positions.append(token.position)

        if self.schema.unique_field not in stored:
            unique_value = document.get(self.schema.unique_field)
            normalized_unique = self._normalize_stored_value(self.schema.unique_field, unique_value)
            if normalized_unique not in (None, ""):
                stored[self.schema.unique_field] = normalized_unique

        self._stored_fields[doc_key] = stored
        return doc_key

    def build(self) -> dict[str, Any]:
        """Build segment data for SQLite storage."""
        postings = {}
        for field_name, terms in self._postings.items():
            postings[field_name] = {}
            for term, doc_map in terms.items():
                postings[field_name][term] = [
                    {
                        "doc_id": doc_id,
                        "positions": list(positions),
                    }
                    for doc_id, positions in doc_map.items()
                ]

        return {
            "segment_id": self.segment_id,
            "created_at": self.created_at.isoformat(),
            "schema": self.schema.to_dict(),
            "postings": postings,
            "stored_fields": dict(self._stored_fields),
            "field_lengths": {field: dict(lengths) for field, lengths in self._field_lengths.items()},
            "doc_count": len(self._stored_fields),
        }

    def _normalize_unique(self, document: dict[str, Any]) -> str:
        """Normalize unique field value."""
        if self.schema.unique_field not in document:
            raise ValueError(f"Document missing unique field '{self.schema.unique_field}'")
        value = document[self.schema.unique_field]
        if value is None:
            raise ValueError(f"Unique field '{self.schema.unique_field}' cannot be None")
        return str(value)

    def _analyze_field(self, field, value):
        """Analyze field value into tokens."""
        if value is None:
            return []
        if isinstance(field, TextField):
            analyzer = get_analyzer(field.analyzer_name)
            return list(analyzer(str(value)))
        if isinstance(field, (KeywordField, NumericField)):
            return list(self._keyword_analyzer(str(value)))
        return []

    def _normalize_stored_value(self, field_name: str, value: Any) -> str | None:
        """Normalize stored field value."""
        if value is None:
            return None
        text = str(value)
        if field_name == "body":
            return text[:4096] if len(text) > 4096 else text
        if field_name == "excerpt":
            return text[:640] if len(text) > 640 else text
        if field_name == "title":
            return text[:512] if len(text) > 512 else text
        return text
