"""Unit tests for SyncMetadataStore helper behaviors."""

from datetime import datetime, timezone
import json
import shutil

import pytest

from docs_mcp_server.utils.sync_metadata_store import SyncMetadataStore


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_save_and_load_url_metadata(tmp_path):
    """Metadata round-trips between save and load."""

    store = SyncMetadataStore(tmp_path)
    payload = {
        "url": "https://example.com/page",
        "next_due_at": datetime.now(timezone.utc).isoformat(),
    }

    await store.save_url_metadata(payload)
    retrieved = await store.load_url_metadata("https://example.com/page")

    assert retrieved is not None
    assert retrieved["url"] == payload["url"]


@pytest.mark.asyncio
async def test_list_all_metadata(tmp_path):
    """Listing metadata returns all stored entries."""

    store = SyncMetadataStore(tmp_path)

    for idx in range(3):
        await store.save_url_metadata({"url": f"https://example.com/{idx}"})

    entries = await store.list_all_metadata()
    assert len(entries) == 3


def test_ensure_ready_recreates_metadata_directory(tmp_path):
    """ensure_ready should recreate the metadata directory if removed."""

    store = SyncMetadataStore(tmp_path)
    meta_dir = store.metadata_root
    shutil.rmtree(meta_dir)
    assert not meta_dir.exists()

    store.ensure_ready()

    assert meta_dir.exists()


@pytest.mark.asyncio
async def test_skip_save_when_url_missing(tmp_path):
    """save_url_metadata should skip entries without a URL."""

    store = SyncMetadataStore(tmp_path)
    await store.save_url_metadata({"title": "Missing URL"})

    assert not list(store.metadata_root.glob("url_*.json"))


@pytest.mark.asyncio
async def test_cleanup_removes_legacy_directories(tmp_path):
    """Legacy sync-meta folders under both roots get removed."""

    legacy_top = tmp_path / "sync-meta-test"
    legacy_top.mkdir()

    legacy_meta = tmp_path / "__docs_metadata" / "sync-meta-test"
    legacy_meta.mkdir(parents=True)

    store = SyncMetadataStore(tmp_path)
    await store.cleanup_legacy_artifacts()

    assert not legacy_top.exists()
    assert not legacy_meta.exists()


@pytest.mark.asyncio
async def test_last_sync_time_round_trip(tmp_path):
    """Last sync timestamps persist as ISO strings."""

    store = SyncMetadataStore(tmp_path)
    now = datetime.now(timezone.utc)

    await store.save_last_sync_time(now)
    retrieved = await store.get_last_sync_time()

    assert retrieved is not None
    assert abs((retrieved - now).total_seconds()) < 1


@pytest.mark.asyncio
async def test_save_and_load_sitemap_snapshot(tmp_path):
    """Sitemap snapshots persist and can be retrieved via snapshot id."""

    store = SyncMetadataStore(tmp_path)
    snapshot = {"entries": [{"loc": "https://example.com"}], "version": 1}

    await store.save_sitemap_snapshot(snapshot, "alpha")
    loaded = await store.get_sitemap_snapshot("alpha")

    assert loaded == snapshot


@pytest.mark.asyncio
async def test_atomic_write_uses_temp_file(tmp_path):
    """_write_json writes sorted payloads and cleans up temp files."""

    store = SyncMetadataStore(tmp_path)
    target = store._key_path("custom")

    payload = {"z": 1, "a": 2}
    await store._write_json(target, payload)

    assert target.exists()
    # Temp file should be cleaned up
    assert not target.with_suffix(target.suffix + ".tmp").exists()
    assert json.loads(target.read_text()) == {"a": 2, "z": 1}


@pytest.mark.asyncio
async def test_read_json_handles_errors(tmp_path):
    """_read_json gracefully handles missing files and invalid JSON."""

    store = SyncMetadataStore(tmp_path)
    missing = store._key_path("missing")
    result_missing = await store._read_json(missing)
    assert result_missing is None

    broken = store._key_path("broken")
    broken.write_text("{not valid json")
    result_broken = await store._read_json(broken)
    assert result_broken is None
