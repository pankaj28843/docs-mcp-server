from __future__ import annotations

from pathlib import Path

import pytest

from docs_mcp_server.config import Settings
from docs_mcp_server.domain.sync_progress import SyncProgress
from docs_mcp_server.service_layer.filesystem_unit_of_work import FileSystemUnitOfWork
from docs_mcp_server.services.cache_service import CacheService
from docs_mcp_server.utils.crawl_state_store import CrawlStateStore
from docs_mcp_server.utils.models import DocPage
from docs_mcp_server.utils.path_builder import PathBuilder
from docs_mcp_server.utils.sync_scheduler import SyncScheduler, SyncSchedulerConfig
from docs_mcp_server.utils.url_translator import UrlTranslator


class _StubFetcher:
    async def fetch_page(self, url: str) -> DocPage:
        return DocPage(
            url=url,
            title="Example",
            content="# Example\n\nBody",
            extraction_method="stub",
        )

    def get_fallback_metrics(self) -> dict[str, int]:
        return {"fallback_attempts": 0, "fallback_successes": 0, "fallback_failures": 0}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_process_persists_markdown_and_metadata(tmp_path: Path) -> None:
    tenant_root = tmp_path / "tenant"
    tenant_root.mkdir(parents=True, exist_ok=True)

    path_builder = PathBuilder()
    translator = UrlTranslator(tenant_root)

    def uow_factory() -> FileSystemUnitOfWork:
        return FileSystemUnitOfWork(tenant_root, translator, path_builder=path_builder)

    settings = Settings(docs_name="Docs", docs_entry_url=["https://example.com/"])
    settings.semantic_cache_enabled = False
    settings.enable_crawler = False

    cache_service = CacheService(settings=settings, uow_factory=uow_factory)
    cache_service._fetcher = _StubFetcher()

    metadata_store = CrawlStateStore(tenant_root)
    progress_store = metadata_store

    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=uow_factory,
        cache_service_factory=lambda: cache_service,
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="demo",
        config=SyncSchedulerConfig(entry_urls=["https://example.com/"]),
    )
    scheduler._active_progress = SyncProgress.create_new("demo")  # pylint: disable=protected-access

    url = "https://example.com/page"
    await metadata_store.enqueue_urls({url}, reason="test", force=True)
    await scheduler._process_url(url)  # pylint: disable=protected-access

    async with uow_factory() as uow:
        document = await uow.documents.get(url)

    assert document is not None
    assert document.metadata.markdown_rel_path is not None
    markdown_path = tenant_root / document.metadata.markdown_rel_path
    assert markdown_path.exists()

    payload = await metadata_store.load_url_metadata(url)
    assert payload is not None
    assert payload["last_status"] == "success"
    assert payload["markdown_rel_path"] == document.metadata.markdown_rel_path
