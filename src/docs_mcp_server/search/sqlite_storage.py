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
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any
from uuid import uuid4

from docs_mcp_server.search.schema import Schema
from docs_mcp_server.search.storage import Posting


class SQLiteConnectionPool:
    """Thread-safe connection pool optimized for read-heavy workloads."""

    def __init__(self, db_path: Path, max_connections: int = 5):
        self.db_path = db_path
        self.max_connections = max_connections
        self._connections: list[sqlite3.Connection] = []
        self._lock = threading.Lock()

    @contextmanager
    def get_connection(self):
        """Get optimized connection from pool."""
        with self._lock:
            conn = self._connections.pop() if self._connections else self._create_connection()

        try:
            yield conn
        finally:
            with self._lock:
                if len(self._connections) < self.max_connections:
                    self._connections.append(conn)
                else:
                    conn.close()

    def _create_connection(self) -> sqlite3.Connection:
        """Create connection with optimal performance settings."""
        conn = sqlite3.connect(self.db_path)
        # Apply SQLite performance optimizations from official docs
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA cache_size = -64000")  # 64MB cache
        conn.execute("PRAGMA mmap_size = 268435456")  # 256MB mmap
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA page_size = 4096")
        conn.execute("PRAGMA cache_spill = FALSE")
        return conn


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

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """Retrieve document using optimized query."""
        with self._pool.get_connection() as conn:
            cursor = conn.execute("SELECT field_data FROM documents WHERE doc_id = ?", (doc_id,))
            row = cursor.fetchone()
            return json.loads(row[0]) if row and row[0] else None

    def get_postings(self, field_name: str, term: str) -> list[Posting]:
        """Get postings with binary position decoding."""
        with self._pool.get_connection() as conn:
            cursor = conn.execute(
                "SELECT doc_id, positions_blob FROM postings WHERE field = ? AND term = ?", (field_name, term)
            )
            postings = []
            for doc_id, positions_blob in cursor:
                positions = array("I")
                if positions_blob:
                    positions.frombytes(positions_blob)
                postings.append(Posting(doc_id=doc_id, positions=positions))
            return postings


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
        cls.MAX_SEGMENTS = max(1, max_segments) if max_segments else cls.DEFAULT_MAX_SEGMENTS

    def save(self, segment_data: dict[str, Any], *, related_files: list[Path | str] | None = None) -> Path:
        """Save segment with optimized SQLite schema."""
        segment_id = segment_data.get("i") or segment_data.get("segment_id") or uuid4().hex
        db_path = self._db_path(segment_id)

        with sqlite3.connect(db_path) as conn:
            self._apply_optimizations(conn)
            self._create_schema(conn)
            self._store_metadata(conn, segment_id, segment_data)
            self._store_postings(conn, segment_data)
            self._store_documents(conn, segment_data)
            self._store_field_lengths(conn, segment_data)
            conn.execute("ANALYZE")  # Update query planner stats

        return db_path

    def _apply_optimizations(self, conn: sqlite3.Connection) -> None:
        """Apply SQLite performance optimizations."""
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA cache_size = -64000")
        conn.execute("PRAGMA mmap_size = 268435456")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA page_size = 4096")
        conn.execute("PRAGMA cache_spill = FALSE")

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
            );

            CREATE TABLE IF NOT EXISTS field_lengths (
                field TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                length INTEGER NOT NULL,
                PRIMARY KEY (field, doc_id)
            );

            CREATE INDEX IF NOT EXISTS idx_postings_field_term ON postings(field, term);
            CREATE INDEX IF NOT EXISTS idx_field_lengths_field ON field_lengths(field);
        """)

    def _store_metadata(self, conn: sqlite3.Connection, segment_id: str, segment_data: dict[str, Any]) -> None:
        """Store segment metadata."""
        schema_data = segment_data.get("s") or segment_data.get("schema", {})
        # Ensure schema has required url field for compatibility
        if "fields" not in schema_data:
            schema_data = {"fields": [{"name": "url", "type": "text", "stored": True}]}

        created_at = segment_data.get("c") or segment_data.get("created_at") or datetime.now(timezone.utc).isoformat()

        metadata = [
            ("segment_id", segment_id),
            ("schema", json.dumps(schema_data)),
            ("created_at", created_at),
        ]
        conn.executemany("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", metadata)

    def _store_postings(self, conn: sqlite3.Connection, segment_data: dict[str, Any]) -> None:
        """Store postings with binary encoding."""
        raw_postings = segment_data.get("p") or segment_data.get("postings", {})
        postings_data = []

        for field_name, terms in raw_postings.items():
            for term, posting_list in terms.items():
                for posting_dict in posting_list:
                    doc_id = posting_dict.get("d") or posting_dict.get("doc_id", "")
                    positions = posting_dict.get("p") or posting_dict.get("positions", [])

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
        raw_stored = segment_data.get("d") or segment_data.get("stored_fields", {})
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

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            metadata = self._load_metadata(conn)

            if not metadata:
                return None

            schema = Schema.from_dict(json.loads(metadata.get("schema", "{}")))
            created_at = datetime.fromisoformat(metadata.get("created_at", datetime.now(timezone.utc).isoformat()))
            doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

            return SqliteSegment(
                schema=schema, db_path=db_path, segment_id=segment_id, created_at=created_at, doc_count=doc_count
            )

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
        return max(db_files, key=lambda p: p.stat().st_mtime).stem

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
        return segments

    def prune_to_segment_ids(self, keep_segment_ids: list[str]) -> None:
        """Remove segments not in keep list."""
        keep_set = set(keep_segment_ids)
        for db_file in self.directory.glob(f"*{self.DB_SUFFIX}"):
            if db_file.stem not in keep_set:
                try:
                    db_file.unlink()
                except OSError:
                    pass  # Ignore errors for consistency with JSON storage

    def _db_path(self, segment_id: str) -> Path:
        """Get database path for segment."""
        return self.directory / f"{segment_id}{self.DB_SUFFIX}"
