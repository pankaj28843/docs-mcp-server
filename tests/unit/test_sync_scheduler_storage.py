"""Storage and telemetry focused tests for SyncScheduler."""

import pytest

from docs_mcp_server.config import Settings
from docs_mcp_server.service_layer.filesystem_unit_of_work import FakeUnitOfWork
from docs_mcp_server.services.cache_service import CacheService
from docs_mcp_server.utils.crawl_state_store import CrawlStateStore
from docs_mcp_server.utils.models import DocPage, ReadabilityContent
from tests.unit.test_sync_scheduler_unit import _DummySettings, _import_sync_scheduler, _progress_store_stub


def _build_doc_page(url: str, title: str) -> DocPage:
    """Construct a DocPage resembling crawler + extractor output."""

    return DocPage(
        url=url,
        title=title,
        content=f"# {title}\n\nBody",
        extraction_method="article_extractor",
        readability_content=ReadabilityContent(
            raw_html="<p>Body</p>",
            extracted_content="Body",
            processed_markdown=f"# {title}\n\nBody",
            excerpt="Body",
            score=None,
            success=True,
            extraction_method="article_extractor",
        ),
    )


class _StubFetcher:
    """Minimal fetcher stub returning a fixed DocPage and metrics."""

    def __init__(self, page: DocPage):
        self._page = page
        self._metrics = {"fallback_attempts": 7, "fallback_successes": 5, "fallback_failures": 2}

    async def fetch_page(self, url: str):
        return self._page

    def get_fallback_metrics(self) -> dict[str, int]:
        return self._metrics


class _FailingCacheService:
    """CacheService-like stub that always reports failures."""

    def __init__(self, reason: str, metrics: dict[str, int]):
        self._reason = reason
        self._metrics = metrics

    async def check_and_fetch_page(self, url: str, *, use_semantic_cache: bool = True):
        return None, False, self._reason

    def get_fetcher_stats(self) -> dict[str, int]:
        return self._metrics


@pytest.mark.unit
class TestSyncSchedulerStorageParity:
    """Ensure scheduler metadata and cache counts stay in lockstep."""

    @pytest.mark.asyncio
    async def test_successful_fetch_updates_metadata_and_storage_counts(self, tmp_path):
        sync_scheduler = _import_sync_scheduler()
        FakeUnitOfWork.clear_shared_store()

        doc_page = _build_doc_page("https://example.com/page", "Example")

        cache_settings = Settings(
            docs_name="Example",
            docs_sitemap_url="https://example.com/sitemap.xml",
            url_whitelist_prefixes="https://example.com/",
        )
        cache_settings.semantic_cache_enabled = False

        cache_service = CacheService(settings=cache_settings, uow_factory=lambda: FakeUnitOfWork())
        cache_service._fetcher = _StubFetcher(doc_page)

        scheduler = sync_scheduler.SyncScheduler(
            settings=_DummySettings(),
            uow_factory=lambda: FakeUnitOfWork(),
            cache_service_factory=lambda cache_service=cache_service: cache_service,
            metadata_store=CrawlStateStore(tmp_path / "meta"),
            progress_store=_progress_store_stub(),
            tenant_codename="unittest",
            config=sync_scheduler.SyncSchedulerConfig(sitemap_urls=["https://example.com/sitemap.xml"]),
        )

        await scheduler._process_url(doc_page.url)

        payload = await scheduler.metadata_store.load_url_metadata(doc_page.url)
        assert payload is not None
        assert payload["last_status"] == "success"
        assert payload["last_failure_reason"] is None

        await scheduler._update_cache_stats()
        assert scheduler.stats.storage_doc_count >= 1

    @pytest.mark.asyncio
    async def test_metadata_success_count_matches_storage_doc_count(self, tmp_path):
        """Successful fetches update metadata + storage in lockstep."""

        sync_scheduler = _import_sync_scheduler()
        FakeUnitOfWork.clear_shared_store()

        cache_settings = Settings(
            docs_name="Example",
            docs_sitemap_url="https://example.com/sitemap.xml",
            url_whitelist_prefixes="https://example.com/",
        )
        cache_settings.semantic_cache_enabled = False

        cache_service = CacheService(settings=cache_settings, uow_factory=lambda: FakeUnitOfWork())
        metadata_store = CrawlStateStore(tmp_path / "meta")

        scheduler = sync_scheduler.SyncScheduler(
            settings=_DummySettings(),
            uow_factory=lambda: FakeUnitOfWork(),
            cache_service_factory=lambda cache_service=cache_service: cache_service,
            metadata_store=metadata_store,
            progress_store=_progress_store_stub(),
            tenant_codename="unittest",
            config=sync_scheduler.SyncSchedulerConfig(sitemap_urls=["https://example.com/sitemap.xml"]),
        )

        pages = [
            _build_doc_page("https://example.com/one", "Doc One"),
            _build_doc_page("https://example.com/two", "Doc Two"),
        ]

        for page in pages:
            cache_service._fetcher = _StubFetcher(page)
            await scheduler._process_url(page.url)

        metadata_entries = await scheduler.metadata_store.list_all_metadata()
        assert len(metadata_entries) == len(pages)

        scheduler._update_metadata_stats(metadata_entries)
        await scheduler._update_cache_stats()

        assert scheduler.stats.metadata_successful == len(pages)
        assert scheduler.stats.storage_doc_count == len(pages)
        assert scheduler.stats.metadata_successful == scheduler.stats.storage_doc_count

    @pytest.mark.asyncio
    async def test_mark_url_failed_records_reason_and_stats(self, tmp_path):
        sync_scheduler = _import_sync_scheduler()
        FakeUnitOfWork.clear_shared_store()

        failure_reason = "fallback_extractor_failed:status=500"
        metrics = {"fallback_attempts": 3, "fallback_successes": 1, "fallback_failures": 2}
        failing_cache = _FailingCacheService(failure_reason, metrics)

        scheduler = sync_scheduler.SyncScheduler(
            settings=_DummySettings(),
            uow_factory=lambda: FakeUnitOfWork(),
            cache_service_factory=lambda cache_service=failing_cache: cache_service,
            metadata_store=CrawlStateStore(tmp_path / "meta"),
            progress_store=_progress_store_stub(),
            tenant_codename="unittest",
            config=sync_scheduler.SyncSchedulerConfig(sitemap_urls=["https://example.com/sitemap.xml"]),
        )

        await scheduler._process_url("https://example.com/unfetchable")

        metadata = await scheduler.metadata_store.list_all_metadata()
        assert metadata
        entry = metadata[0]
        assert entry["last_status"] == "failed"
        assert entry["last_failure_reason"] == failure_reason

        scheduler._update_metadata_stats(metadata)
        assert scheduler.stats.failed_url_count == 1
        assert scheduler.stats.failure_sample[0]["reason"] == failure_reason
        assert scheduler.stats.fallback_attempts == metrics["fallback_attempts"]
        assert scheduler.stats.fallback_failures == metrics["fallback_failures"]
