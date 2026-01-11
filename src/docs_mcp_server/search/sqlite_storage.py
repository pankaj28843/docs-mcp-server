"""SQLite-based storage engine for high-performance search indexing.

Replaces JSON segment storage with SQLite backend to achieve:
- Sub-5ms p95 search latency
- <30MB memory footprint per tenant
- 50% smaller index files
- Binary position encoding for 4x memory reduction
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from docs_mcp_server.search.schema import Schema
from docs_mcp_server.search.storage import Posting


@dataclass(frozen=True, slots=True)
class SqliteSegment:
    """SQLite-backed segment with lazy loading and binary position encoding."""

    schema: Schema
    db_path: Path
    segment_id: str
    created_at: datetime
    doc_count: int

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """Retrieve stored document fields."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT field_data FROM documents WHERE doc_id = ?", (doc_id,))
            row = cursor.fetchone()
            if not row or not row[0]:
                return None
            import json

            return json.loads(row[0])

    def get_postings(self, field_name: str, term: str) -> list[Posting]:
        """Return postings for a specific term in a field."""
        with sqlite3.connect(self.db_path) as conn:
            # Apply advanced performance settings per connection
            conn.execute("PRAGMA cache_size = -64000")
            conn.execute("PRAGMA mmap_size = 268435456")
            conn.execute("PRAGMA temp_store = MEMORY")
            conn.execute("PRAGMA cache_spill = FALSE")
            
            cursor = conn.execute(
                "SELECT doc_id, positions_blob FROM postings WHERE field = ? AND term = ?", (field_name, term)
            )
            postings = []
            for row in cursor:
                # Decode binary positions back to array
                positions = array("I")
                if row[1]:  # positions_blob
                    positions.frombytes(row[1])
                postings.append(Posting(doc_id=row[0], positions=positions))
            return postings


class SqliteSegmentStore:
    """High-performance SQLite storage engine replacing JSON segment store."""

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
        """Override retention when infra config specifies a custom limit."""
        if not max_segments:
            cls.MAX_SEGMENTS = cls.DEFAULT_MAX_SEGMENTS
            return
        cls.MAX_SEGMENTS = max(1, max_segments)

    def save(self, segment_data: dict[str, Any], *, related_files: list[Path | str] | None = None) -> Path:
        """Save segment data to SQLite database."""
        segment_id = segment_data.get("i") or segment_data.get("segment_id") or uuid4().hex
        db_path = self._db_path(segment_id)

        # Create SQLite database with optimized schema
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            # Advanced performance optimizations from SQLite docs
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA cache_size = -64000")  # 64MB cache
            conn.execute("PRAGMA mmap_size = 268435456")  # 256MB mmap
            conn.execute("PRAGMA temp_store = MEMORY")
            conn.execute("PRAGMA page_size = 4096")  # Optimal page size
            conn.execute("PRAGMA cache_spill = FALSE")  # Keep cache in memory
            conn.execute("PRAGMA locking_mode = EXCLUSIVE")  # Single process optimization
            conn.execute("PRAGMA optimize")  # Enable query planner optimizations

            # Create tables
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS postings (
                    field TEXT NOT NULL,
                    term TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    positions_blob BLOB,
                    PRIMARY KEY (field, term, doc_id)
                ) WITHOUT ROWID
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    doc_id TEXT PRIMARY KEY,
                    field_data TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS field_lengths (
                    field TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    length INTEGER NOT NULL,
                    PRIMARY KEY (field, doc_id)
                )
            """)

            # Create indexes for fast lookups
            conn.execute("CREATE INDEX IF NOT EXISTS idx_postings_field_term ON postings(field, term)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_field_lengths_field ON field_lengths(field)")
            
            # Run ANALYZE to update query planner statistics for optimal performance
            conn.execute("ANALYZE")

            # Store metadata
            schema_data = segment_data.get("s") or segment_data.get("schema", {})
            created_at = (
                segment_data.get("c") or segment_data.get("created_at") or datetime.now(timezone.utc).isoformat()
            )

            import json

            conn.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", ("segment_id", segment_id))
            conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", ("schema", json.dumps(schema_data))
            )
            conn.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", ("created_at", created_at))

            # Store postings with binary position encoding
            raw_postings = segment_data.get("p") or segment_data.get("postings", {})
            for field_name, terms in raw_postings.items():
                for term, posting_list in terms.items():
                    for posting_dict in posting_list:
                        doc_id = posting_dict.get("d") or posting_dict.get("doc_id", "")
                        positions = posting_dict.get("p") or posting_dict.get("positions", [])

                        # Convert positions to binary blob for 4x memory reduction
                        positions_array = array("I", (int(pos) for pos in positions))
                        positions_blob = positions_array.tobytes()

                        conn.execute(
                            "INSERT OR REPLACE INTO postings (field, term, doc_id, positions_blob) VALUES (?, ?, ?, ?)",
                            (field_name, term, doc_id, positions_blob),
                        )

            # Store documents
            raw_stored = segment_data.get("d") or segment_data.get("stored_fields", {})
            for doc_id, fields in raw_stored.items():
                import json

                conn.execute(
                    "INSERT OR REPLACE INTO documents (doc_id, field_data) VALUES (?, ?)", (doc_id, json.dumps(fields))
                )

            # Store field lengths
            raw_lengths = segment_data.get("field_lengths", {})
            for field_name, doc_lengths in raw_lengths.items():
                for doc_id, length in doc_lengths.items():
                    conn.execute(
                        "INSERT OR REPLACE INTO field_lengths (field, doc_id, length) VALUES (?, ?, ?)",
                        (field_name, doc_id, length),
                    )

            conn.commit()

        return db_path

    def load(self, segment_id: str) -> SqliteSegment | None:
        """Load a segment by ID if it exists."""
        db_path = self._db_path(segment_id)
        if not db_path.exists():
            return None

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Load metadata
            cursor = conn.execute("SELECT key, value FROM metadata")
            metadata = {row["key"]: row["value"] for row in cursor}

            import json

            schema_data = json.loads(metadata.get("schema", "{}"))
            schema = Schema.from_dict(schema_data)

            created_at_str = metadata.get("created_at", datetime.now(timezone.utc).isoformat())
            created_at = datetime.fromisoformat(created_at_str)

            # Count documents
            cursor = conn.execute("SELECT COUNT(*) as count FROM documents")
            doc_count = cursor.fetchone()["count"]

            return SqliteSegment(
                schema=schema, db_path=db_path, segment_id=segment_id, created_at=created_at, doc_count=doc_count
            )

    def latest(self) -> SqliteSegment | None:
        """Return the latest segment."""
        latest_id = self.latest_segment_id()
        if not latest_id:
            return None
        return self.load(latest_id)

    def latest_segment_id(self) -> str | None:
        """Return the latest segment ID."""
        # For now, find the most recent .db file
        db_files = list(self.directory.glob(f"*{self.DB_SUFFIX}"))
        if not db_files:
            return None

        # Sort by modification time, return most recent
        latest_file = max(db_files, key=lambda p: p.stat().st_mtime)
        return latest_file.stem

    def latest_doc_count(self) -> int | None:
        """Return the latest document count."""
        latest = self.latest()
        return latest.doc_count if latest else None

    def segment_path(self, segment_id: str) -> Path | None:
        """Return the path to the stored segment if it exists."""
        path = self._db_path(segment_id)
        return path if path.exists() else None

    def list_segments(self) -> list[dict[str, Any]]:
        """Return all segment entries."""
        segments = []
        for db_file in self.directory.glob(f"*{self.DB_SUFFIX}"):
            segment_id = db_file.stem
            segment = self.load(segment_id)
            if segment:
                segments.append(
                    {
                        "segment_id": segment_id,
                        "created_at": segment.created_at.isoformat(),
                        "doc_count": segment.doc_count,
                        "files": [db_file.name],
                    }
                )
        return segments

    def prune_to_segment_ids(self, keep_segment_ids):
        """Delete segments not in keep_segment_ids list."""
        keep_set = set(keep_segment_ids)

        # Get all existing segments
        existing_segments = []
        for db_file in self.directory.glob(f"*{self.DB_SUFFIX}"):
            segment_id = db_file.stem
            existing_segments.append((segment_id, db_file))

        # Remove segments not in keep list
        for segment_id, db_file in existing_segments:
            if segment_id not in keep_set:
                try:
                    db_file.unlink()
                except OSError:
                    pass  # Ignore errors, similar to JSON storage

    def _db_path(self, segment_id: str) -> Path:
        """Return path to SQLite database for segment."""
        return self.directory / f"{segment_id}{self.DB_SUFFIX}"
