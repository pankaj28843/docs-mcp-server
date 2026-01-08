from __future__ import annotations

import json
from pathlib import Path

import pytest

from docs_mcp_server.utils.sync_metadata_store import LockLease, SyncMetadataStore


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_last_sync_time_handles_invalid(tmp_path: Path) -> None:
    store = SyncMetadataStore(tmp_path)
    payload = {"last_sync_at": "not-a-date"}
    await store._write_json(store._key_path("meta_last_sync"), payload)  # pylint: disable=protected-access

    assert await store.get_last_sync_time() is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_url_metadata_skips_missing_url(tmp_path: Path) -> None:
    store = SyncMetadataStore(tmp_path)

    await store.save_url_metadata({"title": "Missing"})

    assert list(store.metadata_root.glob("url_*.json")) == []


@pytest.mark.unit
def test_list_all_metadata_skips_invalid_json(tmp_path: Path) -> None:
    store = SyncMetadataStore(tmp_path)
    bad = store.metadata_root / "url_bad.json"
    bad.write_text("{not json}", encoding="utf-8")

    entries = store._list_all_metadata_sync()  # pylint: disable=protected-access

    assert entries == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_json_returns_none_on_decode_error(tmp_path: Path) -> None:
    store = SyncMetadataStore(tmp_path)
    target = store.metadata_root / "bad.json"
    target.write_text("{bad}", encoding="utf-8")

    data = await store._read_json(target)  # pylint: disable=protected-access

    assert data is None


@pytest.mark.unit
def test_release_lock_skips_other_owner(tmp_path: Path) -> None:
    store = SyncMetadataStore(tmp_path)
    lease_path = store._lock_path("crawler")  # pylint: disable=protected-access
    lease_path.write_text(
        json.dumps(
            {
                "name": "crawler",
                "owner": "other",
                "acquired_at": "2024-01-01T00:00:00+00:00",
                "expires_at": "2024-01-01T01:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    lease = LockLease(
        name="crawler",
        owner="me",
        acquired_at=store._read_lock_sync("crawler", lease_path).acquired_at,  # pylint: disable=protected-access
        expires_at=store._read_lock_sync("crawler", lease_path).expires_at,  # pylint: disable=protected-access
        path=lease_path,
    )

    store._release_lock_sync(lease)  # pylint: disable=protected-access

    assert lease_path.exists()


@pytest.mark.unit
def test_read_lock_returns_none_for_missing_timestamps(tmp_path: Path) -> None:
    store = SyncMetadataStore(tmp_path)
    lease_path = store._lock_path("crawler")  # pylint: disable=protected-access
    lease_path.write_text(json.dumps({"name": "crawler"}), encoding="utf-8")

    lease = store._read_lock_sync("crawler", lease_path)  # pylint: disable=protected-access

    assert lease is None
