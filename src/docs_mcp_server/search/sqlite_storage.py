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
from docs_mcp_server.search.models import Posting
from docs_mcp_server.search.schema import KeywordField, NumericField, Schema, TextField
from docs_mcp_server.search.sqlite_pragmas import apply_read_pragmas, apply_write_pragmas


logger = logging.getLogger(__name__)


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
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
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
    _field_lengths: dict[str, dict[str, int]] | None = None
    _postings_cache: dict[str, dict[str, list[Posting]]] | None = None

    def __post_init__(self):
        """Initialize connection pool lazily."""
        if self._pool is None:
            object.__setattr__(self, "_pool", SQLiteConnectionPool(self.db_path))
        if self._postings_cache is None:
            object.__setattr__(self, "_postings_cache", {})

    def get_postings(self, field_name: str, term: str) -> list[Posting]:
        """Get postings for a specific field and term."""
        with self._pool.get_connection() as conn:
            cursor = conn.execute(
                "SELECT doc_id, positions_blob FROM postings WHERE field = ? AND term = ?", (field_name, term)
            )
            postings = []
            for row in cursor:
                doc_id, positions_blob = row
                positions = array("I")
                if positions_blob:
                    positions.frombytes(positions_blob)
                postings.append(Posting(doc_id=doc_id, frequency=len(positions), positions=positions))
            return postings

    def get_field_postings(self, field_name: str) -> dict[str, list[Posting]]:
        """Get all postings for a specific field with caching."""
        if field_name in self._postings_cache:
            return self._postings_cache[field_name]

        postings = {}
        with self._pool.get_connection() as conn:
            cursor = conn.execute("SELECT term, doc_id, positions_blob FROM postings WHERE field = ?", (field_name,))
            for row in cursor:
                term, doc_id, positions_blob = row
                if term not in postings:
                    postings[term] = []

                positions = array("I")
                if positions_blob:
                    positions.frombytes(positions_blob)

                postings[term].append(Posting(doc_id=doc_id, frequency=len(positions), positions=positions))

        self._postings_cache[field_name] = postings
        return postings

    @property
    def postings(self) -> dict[str, dict[str, list[Posting]]]:
        """Get all postings (inefficient - loads everything into memory)."""
        postings = {}
        with self._pool.get_connection() as conn:
            cursor = conn.execute("SELECT field, term, doc_id, positions_blob FROM postings")
            for row in cursor:
                field_name, term, doc_id, positions_blob = row
                if field_name not in postings:
                    postings[field_name] = {}
                if term not in postings[field_name]:
                    postings[field_name][term] = []

                positions = array("I")
                if positions_blob:
                    positions.frombytes(positions_blob)

                postings[field_name][term].append(Posting(doc_id=doc_id, frequency=len(positions), positions=positions))

        return postings

    @property
    def stored_fields(self) -> dict[str, dict[str, Any]]:
        """Get all stored fields."""
        stored_fields = {}
        with self._pool.get_connection() as conn:
            cursor = conn.execute("SELECT doc_id, field_data FROM documents")
            for row in cursor:
                doc_id, field_data_json = row
                if field_data_json:
                    stored_fields[doc_id] = json.loads(field_data_json)
        return stored_fields

    @property
    def field_lengths(self) -> dict[str, dict[str, int]]:
        """Get field lengths from dedicated table."""
        if self._field_lengths is not None:
            return self._field_lengths

        field_lengths = {}
        with self._pool.get_connection() as conn:
            cursor = conn.execute("SELECT field, doc_id, length FROM field_lengths")
            for row in cursor:
                field_name, doc_id, length = row
                if field_name not in field_lengths:
                    field_lengths[field_name] = {}
                field_lengths[field_name][doc_id] = length

        object.__setattr__(self, "_field_lengths", field_lengths)
        return field_lengths

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """Retrieve document using optimized query."""
        with self._pool.get_connection() as conn:
            cursor = conn.execute("SELECT field_data FROM documents WHERE doc_id = ?", (doc_id,))
            row = cursor.fetchone()
            return json.loads(row[0]) if row and row[0] else None

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
            conn = sqlite3.connect(db_path)
            self._apply_optimizations(conn)
            self._create_schema(conn)
            self._store_metadata(conn, segment_id, segment_data)
            self._store_postings(conn, segment_data)
            self._store_documents(conn, segment_data)
            self._store_field_lengths(conn, segment_data)
            conn.execute("ANALYZE")  # Update query planner stats
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
                positions_blob BLOB,
                PRIMARY KEY (field, term, doc_id)
            ) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                field_data TEXT
            ) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS field_lengths (
                field TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                length INTEGER NOT NULL,
                PRIMARY KEY (field, doc_id)
            ) WITHOUT ROWID;

            CREATE INDEX IF NOT EXISTS idx_postings_field_term ON postings(field, term);
            CREATE INDEX IF NOT EXISTS idx_field_lengths_field ON field_lengths(field);
        """)

    def _store_metadata(self, conn: sqlite3.Connection, segment_id: str, segment_data: dict[str, Any]) -> None:
        """Store segment metadata."""
        # Handle both new and legacy key formats
        schema_data = segment_data.get("schema") or segment_data.get("s", {})
        created_at = segment_data.get("created_at") or segment_data.get("c") or datetime.now(timezone.utc).isoformat()

        # Ensure schema has required url field for compatibility
        if isinstance(schema_data, dict) and "fields" not in schema_data:
            schema_data = {"fields": [{"name": "url", "type": "text", "stored": True}]}

        metadata = [
            ("segment_id", segment_id),
            ("schema", json.dumps(schema_data)),
            ("created_at", created_at),
        ]
        conn.executemany("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", metadata)

    def _store_postings(self, conn: sqlite3.Connection, segment_data: dict[str, Any]) -> None:
        """Store postings with binary encoding."""
        # Handle both new and legacy key formats
        raw_postings = segment_data.get("postings") or segment_data.get("p", {})
        postings_data = []

        for field_name, terms in raw_postings.items():
            for term, posting_list in terms.items():
                for posting_dict in posting_list:
                    doc_id = posting_dict.get("doc_id") or posting_dict.get("d", "")
                    positions = posting_dict.get("positions") or posting_dict.get("p", [])

                    # Binary encode positions for memory efficiency
                    positions_array = array("I", (int(pos) for pos in positions))
                    positions_blob = positions_array.tobytes()

                    postings_data.append((field_name, term, doc_id, positions_blob))

        if postings_data:
            conn.executemany(
                "INSERT OR REPLACE INTO postings (field, term, doc_id, positions_blob) VALUES (?, ?, ?, ?)",
                postings_data,
            )

    def _store_documents(self, conn: sqlite3.Connection, segment_data: dict[str, Any]) -> None:
        """Store document fields."""
        # Handle both new and legacy key formats
        raw_stored = segment_data.get("stored_fields") or segment_data.get("d", {})
        if raw_stored:
            documents_data = [(doc_id, json.dumps(fields)) for doc_id, fields in raw_stored.items()]
            conn.executemany("INSERT OR REPLACE INTO documents (doc_id, field_data) VALUES (?, ?)", documents_data)

    def _store_field_lengths(self, conn: sqlite3.Connection, segment_data: dict[str, Any]) -> None:
        """Store field length statistics."""
        raw_lengths = segment_data.get("field_lengths", {})
        lengths_data = []

        for field_name, doc_lengths in raw_lengths.items():
            for doc_id, length in doc_lengths.items():
                lengths_data.append((field_name, doc_id, length))

        if lengths_data:
            conn.executemany(
                "INSERT OR REPLACE INTO field_lengths (field, doc_id, length) VALUES (?, ?, ?)", lengths_data
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

            doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

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
            "title",
            "excerpt",
            "body",
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
