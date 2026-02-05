from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
from unittest.mock import patch

import pytest

from docs_mcp_server.utils.crawl_state_store import (
    _MAX_CONNECT_RETRIES,
    CrawlStateStore,
    DatabaseCriticalError,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cleanup_legacy_artifacts(tmp_path) -> None:
    store = CrawlStateStore(tmp_path)
    legacy = tmp_path / "__scheduler_meta"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "old.json").write_text("{}", encoding="utf-8")

    await store.cleanup_legacy_artifacts()

    assert not legacy.exists()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_and_load_metadata_roundtrip(tmp_path) -> None:
    store = CrawlStateStore(tmp_path)
    now = datetime.now(timezone.utc)
    await store.upsert_url_metadata(
        {
            "url": "https://example.com/doc",
            "last_status": "success",
            "last_fetched_at": now.isoformat(),
            "next_due_at": (now + timedelta(days=1)).isoformat(),
        }
    )

    payload = await store.load_url_metadata("https://example.com/doc")

    assert payload is not None
    assert payload["url"] == "https://example.com/doc"
    assert payload["last_status"] == "success"
    assert payload["last_fetched_at"] == now.isoformat()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enqueue_respects_recent_success_and_force(tmp_path) -> None:
    store = CrawlStateStore(tmp_path)
    now = datetime.now(timezone.utc)

    await store.upsert_url_metadata(
        {
            "url": "https://example.com/recent",
            "last_status": "success",
            "last_fetched_at": now.isoformat(),
            "next_due_at": (now + timedelta(hours=4)).isoformat(),
        }
    )

    await store.enqueue_urls({"https://example.com/recent"}, reason="test")
    assert await store.queue_depth() == 0

    await store.enqueue_urls({"https://example.com/recent"}, reason="forced", force=True)
    assert await store.queue_depth() == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_status_snapshot_aggregates_counts(tmp_path) -> None:
    store = CrawlStateStore(tmp_path)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    await store.upsert_url_metadata(
        {
            "url": "https://example.com/ok",
            "first_seen_at": now_iso,
            "last_status": "success",
            "last_fetched_at": now_iso,
            "next_due_at": now_iso,
        }
    )
    await store.upsert_url_metadata(
        {
            "url": "https://example.com/fail",
            "first_seen_at": now_iso,
            "last_status": "failed",
            "last_failure_at": now_iso,
            "next_due_at": now_iso,
        }
    )
    await store.upsert_url_metadata(
        {
            "url": "https://example.com/pending",
            "first_seen_at": now_iso,
            "last_status": "pending",
            "next_due_at": now_iso,
        }
    )
    await store.enqueue_urls({"https://example.com/fail", "https://example.com/pending"}, reason="test", force=True)

    snapshot = await store.get_status_snapshot()

    assert snapshot["metadata_total_urls"] == 3
    assert snapshot["metadata_successful"] == 1
    assert snapshot["failed_url_count"] == 1
    assert snapshot["metadata_pending"] == 1
    assert snapshot["metadata_due_urls"] == 3
    assert snapshot["queue_depth"] == 2
    assert snapshot["metadata_first_seen_at"] == now_iso
    assert snapshot["metadata_last_success_at"] == now_iso


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dequeue_batch_prioritizes_higher_priority(tmp_path) -> None:
    store = CrawlStateStore(tmp_path)

    await store.enqueue_urls({"https://example.com/low"}, reason="low", priority=0, force=True)
    await store.enqueue_urls({"https://example.com/high"}, reason="high", priority=5, force=True)

    batch = await store.dequeue_batch(1)

    assert batch == ["https://example.com/high"]
    assert await store.queue_depth() == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_was_recently_fetched_sync_tracks_success(tmp_path) -> None:
    store = CrawlStateStore(tmp_path)
    now = datetime.now(timezone.utc)

    await store.upsert_url_metadata(
        {
            "url": "https://example.com/ok",
            "last_status": "success",
            "last_fetched_at": now.isoformat(),
            "next_due_at": (now + timedelta(hours=2)).isoformat(),
        }
    )

    assert store.was_recently_fetched_sync("https://example.com/ok", interval_hours=4) is True

    await store.upsert_url_metadata(
        {
            "url": "https://example.com/ok",
            "last_status": "failed",
            "last_fetched_at": now.isoformat(),
            "next_due_at": (now + timedelta(hours=2)).isoformat(),
        }
    )

    assert store.was_recently_fetched_sync("https://example.com/ok", interval_hours=4) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_event_and_history(tmp_path) -> None:
    store = CrawlStateStore(tmp_path)

    await store.record_event(
        url="https://example.com/success",
        event_type="fetch_success",
        status="ok",
    )
    await store.record_event(
        url="https://example.com/fail",
        event_type="fetch_failure",
        status="failed",
        reason="boom",
    )

    history = await store.get_event_history(minutes=60, bucket_seconds=60)

    assert history["total_events"] == 2
    assert history["status_counts"]["ok"] == 1
    assert history["status_counts"]["failed"] == 1
    assert history["type_counts"]["fetch_success"] == 1
    assert history["type_counts"]["fetch_failure"] == 1

    failed_log = await store.get_event_log(status="failed")
    assert failed_log["count"] == 1
    assert failed_log["events"][0]["event_type"] == "fetch_failure"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maintenance_prunes_old_events(tmp_path) -> None:
    store = CrawlStateStore(tmp_path)
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=90)).isoformat()
    recent = (now - timedelta(days=2)).isoformat()

    with store._connect() as conn:
        conn.execute(
            """
            INSERT INTO crawl_events (event_at, canonical_url, url, event_type, status, reason, detail, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (old, "old", "old", "fetch_success", "ok", None, None, None),
        )
        conn.execute(
            """
            INSERT INTO crawl_events (event_at, canonical_url, url, event_type, status, reason, detail, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (recent, "recent", "recent", "fetch_success", "ok", None, None, None),
        )

    await store.maintenance(event_retention_days=30)

    with store._connect(read_only=True) as conn:
        rows = conn.execute("SELECT event_at FROM crawl_events ORDER BY event_at ASC").fetchall()

    assert len(rows) == 1
    assert rows[0]["event_at"] == recent


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_event_log_filters(tmp_path) -> None:
    store = CrawlStateStore(tmp_path)

    await store.record_event(
        url="https://example.com/a",
        event_type="fetch_success",
        status="ok",
    )
    await store.record_event(
        url="https://example.com/b",
        event_type="crawl_discovered",
        status="ok",
    )

    fetch_log = await store.get_event_log(event_type="fetch_success")
    assert fetch_log["count"] == 1
    assert fetch_log["events"][0]["event_type"] == "fetch_success"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_requeue_failed_urls(tmp_path) -> None:
    store = CrawlStateStore(tmp_path)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    await store.upsert_url_metadata(
        {
            "url": "https://example.com/failed",
            "last_status": "failed",
            "last_failure_at": now_iso,
            "next_due_at": now_iso,
        }
    )
    await store.upsert_url_metadata(
        {
            "url": "https://example.com/success",
            "last_status": "success",
            "last_fetched_at": now_iso,
            "next_due_at": now_iso,
        }
    )

    requeued = await store.requeue_failed_urls()

    assert requeued == 1
    assert await store.queue_depth() == 1
    batch = await store.dequeue_batch(1)
    assert batch == ["https://example.com/failed"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clear_queue_returns_count(tmp_path) -> None:
    store = CrawlStateStore(tmp_path)
    await store.enqueue_urls({"https://example.com/a", "https://example.com/b"}, reason="test", force=True)

    cleared = await store.clear_queue(reason="test_clear")

    assert cleared == 2
    assert await store.queue_depth() == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_break_lock_allows_reacquire(tmp_path) -> None:
    store = CrawlStateStore(tmp_path)
    lease, existing = await store.try_acquire_lock("crawl", "owner-a", ttl_seconds=10)
    assert lease is not None
    assert existing is None

    await store.break_lock("crawl")
    lease, existing = await store.try_acquire_lock("crawl", "owner-b", ttl_seconds=10)
    assert lease is not None
    assert existing is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_was_recently_fetched_async(tmp_path) -> None:
    store = CrawlStateStore(tmp_path)
    now = datetime.now(timezone.utc)
    await store.upsert_url_metadata(
        {
            "url": "https://example.com/recent",
            "last_status": "success",
            "last_fetched_at": now.isoformat(),
            "next_due_at": (now + timedelta(hours=2)).isoformat(),
        }
    )

    assert await store.was_recently_fetched("https://example.com/recent", interval_hours=4) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_checkpoint_with_history(tmp_path) -> None:
    store = CrawlStateStore(tmp_path)
    payload = {"phase": "done", "count": 3}

    await store.save_checkpoint("alpha", payload, keep_history=True)

    with store._connect(read_only=True) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM crawl_checkpoint_history WHERE key = ?", ("alpha",)
        ).fetchone()
    assert row["count"] == 1


@pytest.mark.unit
def test_connect_self_healing_creates_directory(tmp_path) -> None:
    """Self-healing: _connect creates missing directories before connecting."""
    nested_path = tmp_path / "deep" / "nested"
    store = CrawlStateStore(nested_path)

    # Directory should exist after initialization
    assert store.db_root.exists()
    assert store.db_path.exists()


@pytest.mark.unit
def test_connect_retries_on_transient_failure(tmp_path) -> None:
    """Self-healing: _connect retries on transient SQLite errors."""
    store = CrawlStateStore(tmp_path)

    call_count = 0
    original_connect = sqlite3.connect

    def flaky_connect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise sqlite3.OperationalError("disk I/O error")
        return original_connect(*args, **kwargs)

    with (
        patch("sqlite3.connect", side_effect=flaky_connect),
        patch("time.sleep") as mock_sleep,
    ):
        # Should succeed after retry
        conn = store._connect()
        conn.close()

    assert call_count == 2  # First failed, second succeeded
    assert mock_sleep.call_count == 1  # Slept once before retry


@pytest.mark.unit
def test_connect_raises_critical_error_after_max_retries(tmp_path) -> None:
    """Self-healing: raises DatabaseCriticalError after exhausting retries."""
    store = CrawlStateStore(tmp_path)

    def always_fail(*args, **kwargs):
        raise sqlite3.OperationalError("unable to open database file")

    with (
        patch("sqlite3.connect", side_effect=always_fail),
        patch("time.sleep") as mock_sleep,
    ):
        with pytest.raises(DatabaseCriticalError) as exc_info:
            store._connect()

    assert "unable to open database file" in str(exc_info.value)
    assert str(_MAX_CONNECT_RETRIES) in str(exc_info.value)
    # Should only sleep between retries, not after last attempt
    assert mock_sleep.call_count == _MAX_CONNECT_RETRIES - 1


@pytest.mark.unit
def test_database_critical_error_is_runtime_error() -> None:
    """DatabaseCriticalError is a RuntimeError subclass for broad exception handling."""
    assert issubclass(DatabaseCriticalError, RuntimeError)
    err = DatabaseCriticalError("test error")
    assert str(err) == "test error"
