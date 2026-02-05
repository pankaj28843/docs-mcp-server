"""SQLite-backed crawl state store for scheduler metadata, queue, and locks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, ClassVar

from docs_mcp_server.domain.sync_progress import SyncProgress
from docs_mcp_server.search.sqlite_pragmas import apply_read_pragmas, apply_write_pragmas
from docs_mcp_server.utils.path_builder import PathBuilder


logger = logging.getLogger(__name__)


class DatabaseCriticalError(RuntimeError):
    """Unrecoverable database error requiring process restart.

    When raised, the calling application should exit so Docker (or supervisor)
    can restart the container. This implements the self-healing pattern for
    transient filesystem/storage issues.
    """


# Maximum retries for self-healing connection attempts
_MAX_CONNECT_RETRIES = 3
_RETRY_DELAY_SECONDS = 0.5


@dataclass(slots=True)
class LockLease:
    """Represents a SQLite-backed lock lease."""

    name: str
    owner: str
    acquired_at: datetime
    expires_at: datetime

    def is_expired(self, *, now: datetime | None = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        return moment >= self.expires_at

    def remaining_seconds(self, *, now: datetime | None = None) -> float:
        moment = now or datetime.now(timezone.utc)
        return max(0.0, (self.expires_at - moment).total_seconds())


class CrawlStateStore:
    """Persist crawl metadata, queue, locks, and progress in SQLite."""

    SUMMARY_KEY = "summary"
    LAST_SYNC_KEY = "last_sync_at"
    EVENT_RETENTION_DAYS = 49
    EVENT_MAX_ROWS = 200_000
    _ALLOWED_TABLES: ClassVar[set[str]] = {"crawl_urls", "crawl_events"}
    _ALLOWED_COLUMNS: ClassVar[set[str]] = {"fetch_count", "cache_hit_count", "failure_count", "last_event_at"}

    def __init__(
        self,
        tenant_root: Path,
        *,
        db_dir: str = "__crawl_state",
        db_name: str = "crawl.sqlite",
    ) -> None:
        self.tenant_root = tenant_root
        self.db_root = tenant_root / db_dir
        self.db_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_root / db_name
        self._path_builder = PathBuilder()
        self._initialize_schema()

    def ensure_ready(self) -> None:
        self.db_root.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            self._initialize_schema()

    async def cleanup_legacy_artifacts(self) -> None:
        legacy_dirs = ["__scheduler_meta", "__sync_progress"]
        for name in legacy_dirs:
            path = self.tenant_root / name
            if path.exists():
                logger.warning(
                    "Legacy crawl metadata detected at %s (no migration applied).",
                    path,
                )
                logger.info("Removing legacy crawl metadata at %s (no migration applied).", path)
                try:
                    for child in path.rglob("*"):
                        if child.is_file():
                            child.unlink()
                    for child in sorted(path.rglob("*"), reverse=True):
                        if child.is_dir():
                            child.rmdir()
                    path.rmdir()
                except OSError:
                    continue

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        """Connect to SQLite with self-healing retry logic.

        Attempts to recover from transient filesystem issues by:
        1. Ensuring the parent directory exists
        2. Retrying connection with exponential backoff
        3. Raising DatabaseCriticalError after exhausting retries (triggers container restart)

        Note: SQLite operations are inherently blocking. The retry sleep uses time.sleep()
        which is acceptable here since SQLite itself blocks. For truly non-blocking behavior,
        consider using aiosqlite, but that would require a significant refactor.
        """
        last_error: sqlite3.Error | None = None

        for attempt in range(_MAX_CONNECT_RETRIES):
            try:
                # Self-heal: ensure directory exists before each attempt
                self.db_root.mkdir(parents=True, exist_ok=True)

                if read_only:
                    conn = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
                    apply_read_pragmas(conn)
                else:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False, cached_statements=0)
                    apply_write_pragmas(conn)
                    conn.execute("PRAGMA busy_timeout = 30000")
                conn.row_factory = sqlite3.Row
                return conn
            except sqlite3.Error as exc:
                last_error = exc
                # Only sleep if there are more retries remaining
                if attempt < _MAX_CONNECT_RETRIES - 1:
                    delay = _RETRY_DELAY_SECONDS * (2**attempt)
                    logger.warning(
                        "SQLite connect attempt %d/%d failed for %s: %s. Retrying in %.1fs...",
                        attempt + 1,
                        _MAX_CONNECT_RETRIES,
                        self.db_path,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    logger.warning(
                        "SQLite connect attempt %d/%d failed for %s: %s. No retries left.",
                        attempt + 1,
                        _MAX_CONNECT_RETRIES,
                        self.db_path,
                        exc,
                    )

        # All retries exhausted: raise critical error to trigger container restart
        logger.critical(
            "FATAL: Unable to open database at %s after %d attempts: %s. "
            "Triggering process exit for container restart.",
            self.db_path,
            _MAX_CONNECT_RETRIES,
            last_error,
        )
        raise DatabaseCriticalError(
            f"Unable to open database at {self.db_path} after {_MAX_CONNECT_RETRIES} attempts: {last_error}"
        )

    def _initialize_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS crawl_urls (
                    canonical_url TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    discovered_from TEXT,
                    first_seen_at TEXT,
                    last_fetched_at TEXT,
                    next_due_at TEXT,
                    last_status TEXT,
                    retry_count INTEGER,
                    last_failure_reason TEXT,
                    last_failure_at TEXT,
                    markdown_rel_path TEXT,
                    fetch_count INTEGER DEFAULT 0,
                    cache_hit_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    last_event_at TEXT
                );
                CREATE TABLE IF NOT EXISTS crawl_queue (
                    canonical_url TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    enqueued_at TEXT,
                    priority INTEGER DEFAULT 0,
                    reason TEXT
                );
                CREATE TABLE IF NOT EXISTS crawl_locks (
                    name TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS crawl_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS crawl_sitemaps (
                    snapshot_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS crawl_debug (
                    name TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS crawl_summary (
                    key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS crawl_progress (
                    key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS crawl_checkpoint (
                    key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS crawl_checkpoint_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS crawl_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_at TEXT NOT NULL,
                    canonical_url TEXT,
                    url TEXT,
                    event_type TEXT NOT NULL,
                    status TEXT,
                    reason TEXT,
                    detail TEXT,
                    duration_ms INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_crawl_events_url_time ON crawl_events (canonical_url, event_at DESC);
                CREATE INDEX IF NOT EXISTS idx_crawl_events_time ON crawl_events (event_at DESC);
                """
            )
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
            self._ensure_column(conn, "crawl_urls", "fetch_count", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "crawl_urls", "cache_hit_count", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "crawl_urls", "failure_count", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "crawl_urls", "last_event_at", "TEXT")
            self._ensure_table(conn, "crawl_events")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, spec: str) -> None:
        try:
            if not self._is_safe_identifier(table) or not self._is_safe_identifier(column):
                return
            if table not in self._ALLOWED_TABLES or column not in self._ALLOWED_COLUMNS:
                return
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            existing = {row[1] for row in rows}
            if column in existing:
                return
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {spec}")
        except sqlite3.Error:
            return

    def _ensure_table(self, conn: sqlite3.Connection, table: str) -> None:
        if table == "crawl_events":
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS crawl_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_at TEXT NOT NULL,
                    canonical_url TEXT,
                    url TEXT,
                    event_type TEXT NOT NULL,
                    status TEXT,
                    reason TEXT,
                    detail TEXT,
                    duration_ms INTEGER
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_crawl_events_url_time ON crawl_events (canonical_url, event_at DESC)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_crawl_events_time ON crawl_events (event_at DESC)")

    @staticmethod
    def _is_safe_identifier(name: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))

    def _canonicalize(self, url: str) -> str:
        return self._path_builder.canonicalize_url(url)

    def _record_event_sync(
        self,
        conn: sqlite3.Connection,
        *,
        url: str | None,
        canonical: str | None,
        event_type: str,
        status: str | None,
        reason: str | None,
        detail: dict[str, Any] | None,
        duration_ms: int | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(detail, sort_keys=True) if detail else None
        # Events are append-only by design; retries and concurrent processing should be observable.
        conn.execute(
            """
            INSERT INTO crawl_events (event_at, canonical_url, url, event_type, status, reason, detail, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now, canonical, url, event_type, status, reason, payload, duration_ms),
        )
        if canonical:
            conn.execute(
                """
                INSERT OR IGNORE INTO crawl_urls (canonical_url, url, first_seen_at, next_due_at, last_status, retry_count)
                VALUES (?, ?, ?, ?, 'pending', 0)
                """,
                (canonical, url or canonical, now, now),
            )
            conn.execute(
                "UPDATE crawl_urls SET last_event_at = ? WHERE canonical_url = ?",
                (now, canonical),
            )
            if event_type == "cache_hit":
                conn.execute(
                    "UPDATE crawl_urls SET cache_hit_count = cache_hit_count + 1 WHERE canonical_url = ?",
                    (canonical,),
                )
            elif event_type in {"fetch_success", "fetch_failure"}:
                conn.execute(
                    "UPDATE crawl_urls SET fetch_count = fetch_count + 1 WHERE canonical_url = ?",
                    (canonical,),
                )
            if status == "failed":
                conn.execute(
                    "UPDATE crawl_urls SET failure_count = failure_count + 1 WHERE canonical_url = ?",
                    (canonical,),
                )

    async def record_event(
        self,
        *,
        url: str | None,
        event_type: str,
        status: str | None = None,
        reason: str | None = None,
        detail: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        canonical = self._canonicalize(url) if url else None
        with self._connect() as conn:
            self._record_event_sync(
                conn,
                url=url,
                canonical=canonical,
                event_type=event_type,
                status=status,
                reason=reason,
                detail=detail,
                duration_ms=duration_ms,
            )

    async def save_last_sync_time(self, sync_time: datetime) -> None:
        payload = sync_time.isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO crawl_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (self.LAST_SYNC_KEY, payload),
            )

    async def get_last_sync_time(self) -> datetime | None:
        with self._connect(read_only=True) as conn:
            row = conn.execute("SELECT value FROM crawl_meta WHERE key = ?", (self.LAST_SYNC_KEY,)).fetchone()
        if not row or not row["value"]:
            return None
        try:
            return datetime.fromisoformat(row["value"])
        except ValueError:
            return None

    async def save_sitemap_snapshot(self, snapshot: dict, snapshot_id: str) -> None:
        payload = json.dumps(snapshot, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO crawl_sitemaps (snapshot_id, payload) VALUES (?, ?)"
                " ON CONFLICT(snapshot_id) DO UPDATE SET payload=excluded.payload",
                (snapshot_id, payload),
            )

    async def get_sitemap_snapshot(self, snapshot_id: str) -> dict | None:
        with self._connect(read_only=True) as conn:
            row = conn.execute("SELECT payload FROM crawl_sitemaps WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["payload"])
        except json.JSONDecodeError:
            return None

    async def save_debug_snapshot(self, name: str, payload: dict[str, Any]) -> None:
        serialized = json.dumps(payload, sort_keys=True)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO crawl_debug (name, payload, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (name, serialized, now),
            )

    async def save_summary(self, payload: dict[str, Any]) -> None:
        serialized = json.dumps(payload, sort_keys=True)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO crawl_summary (key, payload, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (self.SUMMARY_KEY, serialized, now),
            )

    async def load_summary(self) -> dict[str, Any] | None:
        with self._connect(read_only=True) as conn:
            row = conn.execute("SELECT payload FROM crawl_summary WHERE key = ?", (self.SUMMARY_KEY,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["payload"])
        except json.JSONDecodeError:
            return None

    async def get_status_snapshot(self) -> dict[str, Any]:
        """Return aggregate crawl status metrics from SQLite."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        with self._connect(read_only=True) as conn:
            total = conn.execute("SELECT COUNT(DISTINCT canonical_url) FROM crawl_urls").fetchone()[0]
            success = conn.execute(
                "SELECT COUNT(DISTINCT canonical_url) FROM crawl_urls WHERE last_status = 'success'"
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(DISTINCT canonical_url) FROM crawl_urls WHERE last_status = 'failed'"
            ).fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(DISTINCT canonical_url) FROM crawl_urls WHERE last_status IN ('pending', 'processing')"
            ).fetchone()[0]
            due = conn.execute(
                "SELECT COUNT(*) FROM crawl_urls WHERE next_due_at IS NOT NULL AND next_due_at <= ?",
                (now_iso,),
            ).fetchone()[0]
            queue_depth = conn.execute("SELECT COUNT(*) FROM crawl_queue").fetchone()[0]
            first_seen_at = conn.execute("SELECT MIN(first_seen_at) FROM crawl_urls").fetchone()[0]
            last_success_at = conn.execute(
                "SELECT MAX(last_fetched_at) FROM crawl_urls WHERE last_status = 'success'"
            ).fetchone()[0]
            last_event_at = conn.execute("SELECT MAX(event_at) FROM crawl_events").fetchone()[0]
            summary_row = conn.execute(
                "SELECT payload FROM crawl_summary WHERE key = ?",
                (self.SUMMARY_KEY,),
            ).fetchone()

        storage_doc_count = 0
        summary_payload: dict[str, Any] | None = None
        if summary_row:
            try:
                summary_payload = json.loads(summary_row["payload"])
            except json.JSONDecodeError:
                summary_payload = None
        if summary_payload:
            storage_doc_count = summary_payload.get("storage_doc_count", 0) or 0

        return {
            "captured_at": now_iso,
            "metadata_total_urls": total,
            "metadata_unique_urls": total,
            "metadata_due_urls": due,
            "metadata_successful": success,
            "metadata_pending": pending,
            "metadata_first_seen_at": first_seen_at,
            "metadata_last_success_at": last_success_at,
            "failed_url_count": failed,
            "queue_depth": queue_depth,
            "storage_doc_count": storage_doc_count,
            "last_event_at": last_event_at,
        }

    async def upsert_url_metadata(self, payload: dict[str, Any]) -> None:
        url = payload.get("url")
        if not url:
            logger.debug("Skipping crawl metadata save with missing URL: %s", payload)
            return
        canonical = self._canonicalize(url)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO crawl_urls (
                    canonical_url, url, discovered_from, first_seen_at, last_fetched_at,
                    next_due_at, last_status, retry_count, last_failure_reason,
                    last_failure_at, markdown_rel_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_url) DO UPDATE SET
                    url=excluded.url,
                    discovered_from=COALESCE(excluded.discovered_from, crawl_urls.discovered_from),
                    first_seen_at=COALESCE(crawl_urls.first_seen_at, excluded.first_seen_at),
                    last_fetched_at=excluded.last_fetched_at,
                    next_due_at=excluded.next_due_at,
                    last_status=excluded.last_status,
                    retry_count=excluded.retry_count,
                    last_failure_reason=excluded.last_failure_reason,
                    last_failure_at=excluded.last_failure_at,
                    markdown_rel_path=excluded.markdown_rel_path
                """,
                (
                    canonical,
                    url,
                    payload.get("discovered_from"),
                    payload.get("first_seen_at"),
                    payload.get("last_fetched_at"),
                    payload.get("next_due_at"),
                    payload.get("last_status"),
                    payload.get("retry_count", 0),
                    payload.get("last_failure_reason"),
                    payload.get("last_failure_at"),
                    payload.get("markdown_rel_path"),
                ),
            )

    async def load_url_metadata(self, url: str) -> dict | None:
        canonical = self._canonicalize(url)
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM crawl_urls WHERE canonical_url = ?",
                (canonical,),
            ).fetchone()
        if not row:
            return None
        return dict(row)

    async def list_all_metadata(self) -> list[dict]:
        with self._connect(read_only=True) as conn:
            rows = conn.execute("SELECT * FROM crawl_urls").fetchall()
        return [dict(row) for row in rows]

    async def enqueue_urls(
        self,
        urls: set[str],
        *,
        reason: str,
        priority: int = 0,
        force: bool = False,
    ) -> int:
        if not urls:
            return 0
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        inserted = 0
        url_list = list(urls)
        chunk_size = 200
        conn = self._connect()
        try:
            for start in range(0, len(url_list), chunk_size):
                chunk = url_list[start : start + chunk_size]
                conn.execute("BEGIN")
                for url in chunk:
                    canonical = self._canonicalize(url)
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO crawl_urls (
                            canonical_url, url, first_seen_at, next_due_at, last_status, retry_count
                        ) VALUES (?, ?, ?, ?, 'pending', 0)
                        """,
                        (canonical, url, now, now),
                    )
                    if not force:
                        row = conn.execute(
                            "SELECT last_status, next_due_at FROM crawl_urls WHERE canonical_url = ?",
                            (canonical,),
                        ).fetchone()
                        if row and row["last_status"] == "success" and row["next_due_at"]:
                            try:
                                next_due_at = datetime.fromisoformat(row["next_due_at"])
                            except ValueError:
                                next_due_at = None
                            if next_due_at and next_due_at > now_dt:
                                continue
                    if force:
                        conn.execute(
                            """
                            INSERT INTO crawl_queue (canonical_url, url, enqueued_at, priority, reason)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(canonical_url) DO UPDATE SET
                                url=excluded.url,
                                enqueued_at=excluded.enqueued_at,
                                priority=MAX(crawl_queue.priority, excluded.priority),
                                reason=excluded.reason
                            """,
                            (canonical, url, now, priority, reason),
                        )
                        inserted += conn.execute("SELECT changes()").fetchone()[0]
                    else:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO crawl_queue (canonical_url, url, enqueued_at, priority, reason)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (canonical, url, now, priority, reason),
                        )
                        inserted += conn.execute("SELECT changes()").fetchone()[0]
                    self._record_event_sync(
                        conn,
                        url=url,
                        canonical=canonical,
                        event_type="queue_enqueued",
                        status="ok",
                        reason=reason,
                        detail={"priority": priority, "force": force},
                    )
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return inserted

    async def requeue_failed_urls(
        self,
        *,
        limit: int | None = None,
        reason: str = "retry_failed",
        priority: int = 5,
    ) -> int:
        if limit is not None and limit <= 0:
            return 0
        with self._connect(read_only=True) as conn:
            query = (
                "SELECT url FROM crawl_urls WHERE last_status = 'failed' "
                "ORDER BY (last_failure_at IS NULL), last_failure_at DESC"
            )
            params: tuple[int, ...] = ()
            if limit is not None:
                query += " LIMIT ?"
                params = (limit,)
            rows = conn.execute(query, params).fetchall()
        urls = {row["url"] for row in rows if row["url"]}
        if not urls:
            return 0
        return await self.enqueue_urls(urls, reason=reason, priority=priority, force=True)

    async def dequeue_batch(self, limit: int) -> list[str]:
        if limit <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT canonical_url, url FROM crawl_queue
                ORDER BY priority DESC, enqueued_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            if not rows:
                return []
            canonical_urls = [row["canonical_url"] for row in rows]
            try:
                conn.execute("BEGIN IMMEDIATE")
                # Dequeue is destructive; retry scheduling is handled via crawl_urls metadata on failure.
                conn.executemany(
                    "DELETE FROM crawl_queue WHERE canonical_url = ?",
                    [(canonical,) for canonical in canonical_urls],
                )
                now = datetime.now(timezone.utc).isoformat()
                conn.executemany(
                    "UPDATE crawl_urls SET last_status = 'processing', next_due_at = ? WHERE canonical_url = ?",
                    [(now, canonical) for canonical in canonical_urls],
                )
                for row in rows:
                    self._record_event_sync(
                        conn,
                        url=row["url"],
                        canonical=row["canonical_url"],
                        event_type="queue_dequeued",
                        status="ok",
                        reason=None,
                        detail=None,
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return [row["url"] for row in rows]

    async def remove_from_queue(self, url: str) -> None:
        canonical = self._canonicalize(url)
        with self._connect() as conn:
            conn.execute("DELETE FROM crawl_queue WHERE canonical_url = ?", (canonical,))
            self._record_event_sync(
                conn,
                url=url,
                canonical=canonical,
                event_type="queue_removed",
                status="ok",
                reason=None,
                detail=None,
            )

    async def delete_url_metadata(self, url: str, *, reason: str | None = None) -> None:
        canonical = self._canonicalize(url)
        with self._connect() as conn:
            conn.execute("DELETE FROM crawl_queue WHERE canonical_url = ?", (canonical,))
            conn.execute("DELETE FROM crawl_urls WHERE canonical_url = ?", (canonical,))
            self._record_event_sync(
                conn,
                url=url,
                canonical=canonical,
                event_type="metadata_pruned",
                status="ok",
                reason=reason,
                detail=None,
            )

    async def delete_urls_by_prefix(self, prefix: str) -> int:
        """Delete all URLs matching a prefix pattern.

        Args:
            prefix: URL prefix to match (e.g., 'https://example.com/path/')

        Returns:
            Number of URLs deleted
        """

        def _delete_sync() -> int:
            pattern = prefix + "%"
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) FROM crawl_urls WHERE url LIKE ?", (pattern,)).fetchone()
                count = row[0] if row else 0
                if count > 0:
                    conn.execute("DELETE FROM crawl_queue WHERE url LIKE ?", (pattern,))
                    conn.execute("DELETE FROM crawl_urls WHERE url LIKE ?", (pattern,))
                    logger.info(f"Deleted {count} URLs matching prefix: {prefix}")
                return count

        return await asyncio.to_thread(_delete_sync)

    async def delete_urls_by_prefixes(self, prefixes: list[str]) -> dict[str, int]:
        """Bulk delete URLs matching multiple prefixes in a single transaction.

        More efficient than calling delete_urls_by_prefix in a loop since it
        uses a single database transaction and releases the lock faster.

        Args:
            prefixes: List of URL prefixes to match

        Returns:
            Dictionary mapping prefix to count of deleted URLs
        """

        def _delete_bulk_sync() -> dict[str, int]:
            results: dict[str, int] = {}
            with self._connect() as conn:
                for prefix in prefixes:
                    pattern = prefix + "%"
                    row = conn.execute("SELECT COUNT(*) FROM crawl_urls WHERE url LIKE ?", (pattern,)).fetchone()
                    count = row[0] if row else 0
                    if count > 0:
                        conn.execute("DELETE FROM crawl_queue WHERE url LIKE ?", (pattern,))
                        conn.execute("DELETE FROM crawl_urls WHERE url LIKE ?", (pattern,))
                    results[prefix] = count
            total = sum(results.values())
            if total > 0:
                logger.info(f"Bulk deleted {total} URLs across {len(prefixes)} prefixes")
            return results

        return await asyncio.to_thread(_delete_bulk_sync)

    async def queue_depth(self) -> int:
        with self._connect(read_only=True) as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM crawl_queue").fetchone()
        return int(row["count"]) if row else 0

    async def was_recently_fetched(self, url: str, *, interval_hours: float) -> bool:
        canonical = self._canonicalize(url)
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT last_fetched_at, last_status FROM crawl_urls WHERE canonical_url = ?",
                (canonical,),
            ).fetchone()
        if not row:
            return False
        last_fetched = row["last_fetched_at"]
        if not last_fetched or row["last_status"] != "success":
            return False
        try:
            fetched_at = datetime.fromisoformat(last_fetched)
        except ValueError:
            return False
        age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
        return age_hours < interval_hours

    def was_recently_fetched_sync(self, url: str, *, interval_hours: float) -> bool:
        canonical = self._canonicalize(url)
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT last_fetched_at, last_status FROM crawl_urls WHERE canonical_url = ?",
                (canonical,),
            ).fetchone()
        if not row:
            return False
        last_fetched = row["last_fetched_at"]
        if not last_fetched or row["last_status"] != "success":
            return False
        try:
            fetched_at = datetime.fromisoformat(last_fetched)
        except ValueError:
            return False
        age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
        return age_hours < interval_hours

    async def try_acquire_lock(
        self, name: str, owner: str, ttl_seconds: int
    ) -> tuple[LockLease | None, LockLease | None]:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)
        payload = (name, owner, now.isoformat(), expires_at.isoformat())
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO crawl_locks (name, owner, acquired_at, expires_at) VALUES (?, ?, ?, ?)",
                    payload,
                )
                return (
                    LockLease(name=name, owner=owner, acquired_at=now, expires_at=expires_at),
                    None,
                )
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT name, owner, acquired_at, expires_at FROM crawl_locks WHERE name = ?",
                    (name,),
                ).fetchone()
        if not row:
            return None, None
        existing = LockLease(
            name=row["name"],
            owner=row["owner"],
            acquired_at=datetime.fromisoformat(row["acquired_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
        )
        return None, existing

    async def release_lock(self, lease: LockLease) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM crawl_locks WHERE name = ? AND owner = ?", (lease.name, lease.owner))

    async def clear_queue(self, *, reason: str | None = None) -> int:
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT COUNT(*) AS count FROM crawl_queue").fetchone()
                count = int(row["count"]) if row else 0
                conn.execute("DELETE FROM crawl_queue")
                if reason:
                    self._record_event_sync(
                        conn,
                        url=None,
                        canonical=None,
                        event_type="queue_cleared",
                        status="ok",
                        reason=reason,
                        detail={"count": count},
                    )
                conn.commit()
                return count
            except Exception:
                conn.rollback()
                raise

    async def break_lock(self, name: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM crawl_locks WHERE name = ?", (name,))

    async def save_progress(self, key: str, payload: dict[str, Any]) -> None:
        serialized = json.dumps(payload, sort_keys=True)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO crawl_progress (key, payload, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (key, serialized, now),
            )

    async def load_progress(self, key: str) -> dict[str, Any] | None:
        with self._connect(read_only=True) as conn:
            row = conn.execute("SELECT payload FROM crawl_progress WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["payload"])
        except json.JSONDecodeError:
            return None

    async def delete_progress(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM crawl_progress WHERE key = ?", (key,))
            conn.execute("DELETE FROM crawl_checkpoint WHERE key = ?", (key,))
            conn.execute("DELETE FROM crawl_checkpoint_history WHERE key = ?", (key,))

    async def _save_checkpoint_payload(self, key: str, payload: dict[str, Any], *, keep_history: bool = False) -> None:
        serialized = json.dumps(payload, sort_keys=True)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO crawl_checkpoint (key, payload, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (key, serialized, now),
            )
            if keep_history:
                conn.execute(
                    "INSERT INTO crawl_checkpoint_history (key, payload, created_at) VALUES (?, ?, ?)",
                    (key, serialized, now),
                )

    async def maintenance(
        self,
        *,
        event_retention_days: int | None = None,
        event_max_rows: int | None = None,
    ) -> None:
        """Run maintenance (event pruning + checkpoint/vacuum) on crawl DB."""
        retention_days = event_retention_days or self.EVENT_RETENTION_DAYS
        max_rows = event_max_rows or self.EVENT_MAX_ROWS
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=retention_days)).isoformat()

        with self._connect() as conn:
            conn.execute("PRAGMA busy_timeout = 2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                logger.debug("Skipping maintenance; crawl DB busy: %s", exc)
                return
            try:
                deleted = conn.execute("DELETE FROM crawl_events WHERE event_at < ?", (cutoff,)).rowcount
                row = conn.execute("SELECT COUNT(*) AS count FROM crawl_events").fetchone()
                total = int(row["count"]) if row else 0
                if total > max_rows:
                    trim = total - max_rows
                    conn.execute(
                        """
                        DELETE FROM crawl_events
                        WHERE id IN (
                            SELECT id FROM crawl_events
                            ORDER BY event_at ASC
                            LIMIT ?
                        )
                        """,
                        (trim,),
                    )
                    deleted += trim
                conn.commit()
            except Exception:
                conn.rollback()
                raise

            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                if deleted > 0:
                    try:
                        auto_vacuum = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
                    except Exception:
                        auto_vacuum = 0
                    if auto_vacuum == 0:
                        conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
                    try:
                        freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
                    except Exception:
                        freelist = 0
                    if freelist:
                        conn.execute("PRAGMA incremental_vacuum(2000)")
            except sqlite3.OperationalError as exc:
                logger.debug("Skipping checkpoint/vacuum due to lock: %s", exc)

    async def get_event_history(
        self,
        *,
        minutes: int = 60,
        range_days: int | None = None,
        bucket_seconds: int = 60,
        limit: int = 5000,
    ) -> dict[str, Any]:
        """Return a time-bucketed history of crawl events."""

        now = datetime.now(timezone.utc)
        if range_days is not None:
            cutoff = (now - timedelta(days=range_days)).isoformat()
        else:
            cutoff = (now - timedelta(minutes=minutes)).isoformat()
        with self._connect(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT event_at, event_type, status
                FROM crawl_events
                WHERE event_at >= ?
                ORDER BY event_at ASC
                LIMIT ?
                """,
                (cutoff, limit),
            ).fetchall()

        buckets: dict[str, dict[str, int]] = {}
        status_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        last_event_at: str | None = None

        for row in rows:
            event_at = row["event_at"]
            if not event_at:
                continue
            try:
                parsed = datetime.fromisoformat(event_at)
            except (TypeError, ValueError):
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            last_event_at = event_at
            bucket_epoch = int(parsed.timestamp() // bucket_seconds * bucket_seconds)
            bucket_dt = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)
            key = bucket_dt.isoformat()
            bucket = buckets.setdefault(
                key,
                {"t": bucket_dt.isoformat(), "total": 0, "success": 0, "failed": 0, "discovered": 0, "fetched": 0},
            )
            bucket["total"] += 1
            status = row["status"]
            status_counts[status] = status_counts.get(status, 0) + 1
            if status == "failed":
                bucket["failed"] += 1
            else:
                bucket["success"] += 1
            event_type = row["event_type"]
            type_counts[event_type] = type_counts.get(event_type, 0) + 1
            if event_type == "crawl_discovered":
                bucket["discovered"] += 1
            if event_type in {"fetch_success", "cache_hit"}:
                bucket["fetched"] += 1

        ordered = [buckets[key] for key in sorted(buckets.keys())]
        return {
            "range_minutes": minutes,
            "range_days": range_days,
            "bucket_seconds": bucket_seconds,
            "last_event_at": last_event_at,
            "total_events": len(rows),
            "status_counts": status_counts,
            "type_counts": type_counts,
            "buckets": ordered,
        }

    async def get_event_log(
        self,
        *,
        limit: int = 200,
        event_type: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Return recent crawl events for drill-down tabs."""
        clauses = []
        params: list[Any] = []
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT event_at, event_type, status, url, reason, detail, duration_ms
            FROM crawl_events
            {where}
            ORDER BY event_at DESC
            LIMIT ?
        """
        params.append(limit)
        with self._connect(read_only=True) as conn:
            rows = conn.execute(sql, params).fetchall()
        events = [
            {
                "event_at": row["event_at"],
                "event_type": row["event_type"],
                "status": row["status"],
                "url": row["url"],
                "reason": row["reason"],
                "detail": row["detail"],
                "duration_ms": row["duration_ms"],
            }
            for row in rows
        ]
        return {"events": events, "count": len(events)}

    # Compatibility surface for SyncProgressStore usage.
    async def save(self, progress: Any) -> None:
        await self.save_progress(progress.tenant_codename, progress.to_dict())

    async def load(self, tenant_codename: str) -> Any | None:
        payload = await self.load_progress(tenant_codename)
        if not payload:
            return None
        try:
            return SyncProgress.from_dict(payload)
        except Exception:
            return None

    async def get_latest_for_tenant(self, tenant_codename: str) -> Any | None:
        return await self.load(tenant_codename)

    async def delete(self, tenant_codename: str) -> None:
        await self.delete_progress(tenant_codename)

    async def save_checkpoint(
        self, tenant_codename: str, checkpoint: dict[str, Any], *, keep_history: bool = False
    ) -> None:
        await self._save_checkpoint_payload(tenant_codename, checkpoint, keep_history=keep_history)
