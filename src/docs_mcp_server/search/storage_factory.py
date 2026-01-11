"""Storage factory for choosing between JSON and SQLite backends."""

from pathlib import Path
from typing import Any

from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore
from docs_mcp_server.search.storage import IndexSegment, JsonSegmentStore


class UnifiedSegmentStore:
    """Unified interface that handles both JSON and SQLite storage."""

    def __init__(self, segments_dir: Path, *, use_sqlite: bool = False):
        self._use_sqlite = use_sqlite
        if use_sqlite:
            self._store = SqliteSegmentStore(segments_dir)
        else:
            self._store = JsonSegmentStore(segments_dir)

    def save(self, segment: IndexSegment | dict[str, Any], **kwargs) -> Path:
        """Save segment, handling both IndexSegment and dict inputs."""
        if self._use_sqlite:
            # SQLite storage expects dict
            if isinstance(segment, IndexSegment):
                return self._store.save(segment.to_dict(), **kwargs)
            return self._store.save(segment, **kwargs)
        # JSON storage expects IndexSegment
        if isinstance(segment, dict):
            segment = IndexSegment.from_dict(segment)
        return self._store.save(segment, **kwargs)

    def load(self, segment_id: str):
        """Load segment by ID."""
        return self._store.load(segment_id)

    def latest(self):
        """Get latest segment."""
        return self._store.latest()

    def latest_segment_id(self) -> str | None:
        """Get latest segment ID."""
        return self._store.latest_segment_id()

    def latest_doc_count(self) -> int | None:
        """Get latest document count."""
        return self._store.latest_doc_count()

    def segment_path(self, segment_id: str) -> Path | None:
        """Get segment path."""
        return self._store.segment_path(segment_id)

    def list_segments(self) -> list[dict[str, Any]]:
        """List all segments."""
        return self._store.list_segments()

    def prune_to_segment_ids(self, keep_segment_ids):
        """Prune segments."""
        return self._store.prune_to_segment_ids(keep_segment_ids)


def create_segment_store(segments_dir: Path, *, use_sqlite: bool = False) -> UnifiedSegmentStore:
    """Create appropriate segment store based on configuration."""
    return UnifiedSegmentStore(segments_dir, use_sqlite=use_sqlite)


def get_latest_doc_count(segments_dir: Path, *, use_sqlite: bool = False) -> int | None:
    """Get latest document count from appropriate storage backend."""
    store = create_segment_store(segments_dir, use_sqlite=use_sqlite)
    return store.latest_doc_count()


def has_search_index(segments_dir: Path, *, use_sqlite: bool = False) -> bool:
    """Check if search index exists in appropriate storage backend."""
    if not segments_dir.exists():
        return False
    store = create_segment_store(segments_dir, use_sqlite=use_sqlite)
    return store.latest_segment_id() is not None
