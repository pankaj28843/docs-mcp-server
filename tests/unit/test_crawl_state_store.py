from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from docs_mcp_server.utils.crawl_state_store import CrawlStateStore


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
