from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from docs_mcp_server.deployment_config import SharedInfraConfig, TenantConfig
from docs_mcp_server.search.indexer import IndexBuildResult
from docs_mcp_server.search.schema import create_default_schema
from docs_mcp_server.search.storage import JsonSegmentStore, SegmentWriter
from docs_mcp_server.services.git_sync_scheduler_service import GitSyncSchedulerService
from docs_mcp_server.services.scheduler_service import SchedulerService
from docs_mcp_server.tenant import IndexRuntime, StorageContext, SyncRuntime


def _make_tenant_config(tmp_path: Path, *, source_type: str = "online") -> TenantConfig:
    tenant = TenantConfig(
        codename="alpha",
        docs_name="Alpha",
        docs_sitemap_url=["https://example.com/sitemap.xml"],
        docs_root_dir=str(tmp_path),
        source_type=source_type,
        git_repo_url="https://example.com/repo.git" if source_type == "git" else None,
        git_subpaths=["docs"] if source_type == "git" else None,
    )
    tenant._infrastructure = SharedInfraConfig()  # attach infra explicitly for unit tests
    return tenant


@pytest.mark.unit
def test_has_search_index_false_when_missing_segments(tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)
    storage = StorageContext(tenant)
    runtime = IndexRuntime(tenant, storage, allow_index_builds=True, enable_residency=False)

    assert runtime.has_search_index() is False


@pytest.mark.unit
def test_has_search_index_true_when_segment_exists(tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)
    storage = StorageContext(tenant)
    runtime = IndexRuntime(tenant, storage, allow_index_builds=True, enable_residency=False)

    segments_dir = storage.storage_path / "__search_segments"
    store = JsonSegmentStore(segments_dir)
    writer = SegmentWriter(create_default_schema())
    writer.add_document({"url": "https://example.com", "title": "Doc", "body": "Body"})
    segment = writer.build()
    store.save(segment)

    assert runtime.has_search_index() is True


@pytest.mark.unit
def test_storage_context_cleans_orphaned_staging_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)

    monkeypatch.setattr(
        "docs_mcp_server.tenant.cleanup_orphaned_staging_dirs",
        lambda *_args, **_kwargs: 2,
    )

    storage = StorageContext(tenant)

    assert storage.storage_path.exists()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_search_index_raises_when_disabled(tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)
    storage = StorageContext(tenant)
    runtime = IndexRuntime(tenant, storage, allow_index_builds=False, enable_residency=False)

    with pytest.raises(RuntimeError):
        await runtime.build_search_index()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_search_index_invokes_indexer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)
    storage = StorageContext(tenant)
    runtime = IndexRuntime(tenant, storage, allow_index_builds=True, enable_residency=False)

    captured = {"limit": None, "invalidated": False}

    class StubIndexer:
        def __init__(self, context) -> None:
            self.context = context

        def build_segment(self, *, limit: int | None = None, **kwargs):
            captured["limit"] = limit
            return IndexBuildResult(
                documents_indexed=2,
                documents_skipped=1,
                errors=("oops",),
                segment_ids=("seg",),
                segment_paths=(),
            )

    async def run_inline(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("docs_mcp_server.search.indexer.TenantIndexer", StubIndexer)
    monkeypatch.setattr(asyncio, "to_thread", run_inline)
    monkeypatch.setattr(runtime, "invalidate_search_cache", lambda: captured.__setitem__("invalidated", True))

    indexed, skipped = await runtime.build_search_index(limit=5)

    assert (indexed, skipped) == (2, 1)
    assert captured["limit"] == 5
    assert captured["invalidated"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_search_index_lazy_returns_true_when_existing(tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)
    storage = StorageContext(tenant)
    runtime = IndexRuntime(tenant, storage, allow_index_builds=False, enable_residency=False)

    segments_dir = storage.storage_path / "__search_segments"
    store = JsonSegmentStore(segments_dir)
    writer = SegmentWriter(create_default_schema())
    writer.add_document({"url": "https://example.com", "title": "Doc", "body": "Body"})
    segment = writer.build()
    store.save(segment)

    assert await runtime.ensure_search_index_lazy() is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_search_index_lazy_builds_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)
    storage = StorageContext(tenant)
    runtime = IndexRuntime(tenant, storage, allow_index_builds=True, enable_residency=False)

    async def fake_build(limit: int | None = None):
        return (1, 0)

    monkeypatch.setattr(runtime, "build_search_index", fake_build)

    assert await runtime.ensure_search_index_lazy() is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_search_index_lazy_handles_build_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)
    storage = StorageContext(tenant)
    runtime = IndexRuntime(tenant, storage, allow_index_builds=True, enable_residency=False)

    async def raise_error():
        raise RuntimeError("boom")

    monkeypatch.setattr(runtime, "build_search_index", raise_error)

    assert await runtime.ensure_search_index_lazy() is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_search_index_lazy_raises_when_disabled(tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)
    storage = StorageContext(tenant)
    runtime = IndexRuntime(tenant, storage, allow_index_builds=False, enable_residency=False)

    with pytest.raises(RuntimeError):
        await runtime.ensure_search_index_lazy()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_search_index_lazy_schedules_refresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)
    storage = StorageContext(tenant)
    runtime = IndexRuntime(tenant, storage, allow_index_builds=True, enable_residency=True)
    runtime._index_verified = True

    async def fake_refresh():
        return (0, 0)

    monkeypatch.setattr(runtime, "_run_background_index_refresh", fake_refresh)

    assert await runtime.ensure_search_index_lazy() is True

    if runtime._background_index_task is not None:
        await runtime._background_index_task
    assert runtime._background_index_completed is True


@pytest.mark.unit
def test_schedule_background_index_refresh_returns_when_disabled(tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)
    storage = StorageContext(tenant)
    runtime = IndexRuntime(tenant, storage, allow_index_builds=False, enable_residency=True)

    runtime._schedule_background_index_refresh()

    assert runtime._background_index_task is None


@pytest.mark.unit
def test_schedule_background_index_refresh_returns_when_residency_disabled(tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)
    storage = StorageContext(tenant)
    runtime = IndexRuntime(tenant, storage, allow_index_builds=True, enable_residency=False)

    runtime._schedule_background_index_refresh()

    assert runtime._background_index_task is None


@pytest.mark.unit
def test_schedule_background_index_refresh_returns_when_completed(tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)
    storage = StorageContext(tenant)
    runtime = IndexRuntime(tenant, storage, allow_index_builds=True, enable_residency=True)
    runtime._background_index_completed = True

    runtime._schedule_background_index_refresh()

    assert runtime._background_index_task is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_background_index_refresh_done_cancelled(tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)
    storage = StorageContext(tenant)
    runtime = IndexRuntime(tenant, storage, allow_index_builds=True, enable_residency=True)

    task = asyncio.create_task(asyncio.sleep(0.01))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    runtime._handle_background_index_refresh_done(task)

    assert runtime._background_index_task is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_shutdown_stops_resident_and_cancels_task(tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)
    storage = StorageContext(tenant)
    runtime = IndexRuntime(tenant, storage, allow_index_builds=True, enable_residency=True)

    called = {"stopped": False}

    class DummySearchService:
        async def stop_resident(self, path: Path) -> None:
            called["stopped"] = True

        def invalidate_cache(self, path: Path) -> None:
            return None

    runtime._search_service = DummySearchService()
    runtime._background_index_task = asyncio.create_task(asyncio.sleep(0.01))

    await runtime.shutdown()

    assert called["stopped"] is True
    assert runtime._index_resident is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_shutdown_no_search_service_noop(tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path)
    storage = StorageContext(tenant)
    runtime = IndexRuntime(tenant, storage, allow_index_builds=True, enable_residency=True)

    await runtime.shutdown()

    assert runtime._index_resident is False


@pytest.mark.unit
def test_sync_runtime_requires_infrastructure(tmp_path: Path) -> None:
    tenant = TenantConfig(
        codename="alpha",
        docs_name="Alpha",
        docs_sitemap_url=["https://example.com/sitemap.xml"],
        docs_root_dir=str(tmp_path),
    )
    storage = StorageContext(tenant)

    with pytest.raises(RuntimeError):
        SyncRuntime(
            tenant,
            storage,
            IndexRuntime(tenant, storage, allow_index_builds=True, enable_residency=False),
            infra_config=SharedInfraConfig(),
        )


@pytest.mark.unit
def test_sync_runtime_git_syncer_and_scheduler(tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path, source_type="git")
    storage = StorageContext(tenant)
    index_runtime = IndexRuntime(tenant, storage, allow_index_builds=True, enable_residency=False)
    runtime = SyncRuntime(tenant, storage, index_runtime, infra_config=tenant._infrastructure)

    scheduler = runtime.get_scheduler_service()
    assert isinstance(scheduler, GitSyncSchedulerService)
    assert scheduler.git_syncer.config.repo_url == tenant.git_repo_url


@pytest.mark.unit
def test_sync_runtime_scheduler_service_for_non_git(tmp_path: Path) -> None:
    tenant = _make_tenant_config(tmp_path, source_type="online")
    storage = StorageContext(tenant)
    index_runtime = IndexRuntime(tenant, storage, allow_index_builds=True, enable_residency=False)
    runtime = SyncRuntime(tenant, storage, index_runtime, infra_config=tenant._infrastructure)

    scheduler = runtime.get_scheduler_service()
    assert isinstance(scheduler, SchedulerService)
