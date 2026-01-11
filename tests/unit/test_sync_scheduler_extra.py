import asyncio
from datetime import datetime, timedelta, timezone
import importlib
import sys
import types

import pytest


def _ensure_stub_modules():
    """Create minimal stub modules to avoid circular imports when importing sync_scheduler in isolation."""
    # docs_mcp_server.config.Settings
    if "docs_mcp_server.config" not in sys.modules:
        m = types.ModuleType("docs_mcp_server.config")

        class Settings:
            pass

        m.Settings = Settings
        sys.modules["docs_mcp_server.config"] = m

    # docs_mcp_server.domain.sync_progress
    if "docs_mcp_server.domain.sync_progress" not in sys.modules:
        m = types.ModuleType("docs_mcp_server.domain.sync_progress")

        class InvalidPhaseTransitionError(Exception):
            pass

        class SyncPhase:
            INITIALIZING = 0
            INTERRUPTED = 1
            FAILED = 2

        class SyncProgress:
            @classmethod
            def create_new(cls, tenant):
                inst = cls()
                inst.pending_urls = set()
                inst.phase = SyncPhase.INITIALIZING
                inst.can_resume = False
                inst.is_complete = False
                return inst

            def create_checkpoint(self):
                return {}

            def mark_url_processed(self, url):
                return None

            def mark_url_failed(self, url, error_type=None, error_message=None):
                return None

            def mark_url_skipped(self, url, reason=None):
                return None

            def mark_completed(self):
                return None

            def mark_failed(self, error=None):
                return None

        m.InvalidPhaseTransitionError = InvalidPhaseTransitionError
        m.SyncPhase = SyncPhase
        m.SyncProgress = SyncProgress
        sys.modules["docs_mcp_server.domain.sync_progress"] = m

    # service_layer.filesystem_unit_of_work.AbstractUnitOfWork
    if "docs_mcp_server.service_layer.filesystem_unit_of_work" not in sys.modules:
        m = types.ModuleType("docs_mcp_server.service_layer.filesystem_unit_of_work")

        class AbstractUnitOfWork:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        m.AbstractUnitOfWork = AbstractUnitOfWork
        sys.modules["docs_mcp_server.service_layer.filesystem_unit_of_work"] = m

    # services.cache_service.CacheService
    if "docs_mcp_server.services.cache_service" not in sys.modules:
        m = types.ModuleType("docs_mcp_server.services.cache_service")

        class CacheService:
            pass

        m.CacheService = CacheService
        sys.modules["docs_mcp_server.services.cache_service"] = m

    # article_extractor.discovery.CrawlConfig, EfficientCrawler
    if "article_extractor.discovery" not in sys.modules:
        m = types.ModuleType("article_extractor.discovery")

        class CrawlConfig:
            def __init__(self, *args, **kwargs):
                pass

        class EfficientCrawler:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def crawl(self):
                return set()

        m.CrawlConfig = CrawlConfig
        m.EfficientCrawler = EfficientCrawler
        sys.modules["article_extractor.discovery"] = m

    # utils.models.SitemapEntry
    if "docs_mcp_server.utils.models" not in sys.modules:
        m = types.ModuleType("docs_mcp_server.utils.models")

        class SitemapEntry:
            def __init__(self, url, lastmod=None):
                self.url = url
                self.lastmod = lastmod

        m.SitemapEntry = SitemapEntry
        sys.modules["docs_mcp_server.utils.models"] = m

    # utils.sync_metadata_store
    if "docs_mcp_server.utils.sync_metadata_store" not in sys.modules:
        m = types.ModuleType("docs_mcp_server.utils.sync_metadata_store")

        class LockLease:
            def __init__(self, lock_id, lease_id, expires_at):
                self.lock_id = lock_id
                self.lease_id = lease_id
                self.expires_at = expires_at

        class SyncMetadataStore:
            pass

        m.LockLease = LockLease
        m.SyncMetadataStore = SyncMetadataStore
        sys.modules["docs_mcp_server.utils.sync_metadata_store"] = m

    # utils.sync_progress_store
    if "docs_mcp_server.utils.sync_progress_store" not in sys.modules:
        m = types.ModuleType("docs_mcp_server.utils.sync_progress_store")

        class SyncProgressStore:
            pass

        m.SyncProgressStore = SyncProgressStore
        sys.modules["docs_mcp_server.utils.sync_progress_store"] = m


def get_scheduler_classes():
    _ensure_stub_modules()
    mod = importlib.import_module("docs_mcp_server.utils.sync_scheduler")
    return mod.SyncScheduler, mod.SyncSchedulerConfig


class FakeCrawler:
    def __init__(self, root_urls, config, settings=None):
        self._root = root_urls
        self._crawler_skipped = 2

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def crawl(self):
        # Simulate discovering two pages
        return set(self._root).union({"https://root/page1", "https://root/page2"})


class FakeResponse:
    def __init__(self, content=b"<urlset></urlset>", status=200):
        self.content = content
        self.status_code = status
        self.url = "https://example.com/sitemap.xml"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP error")


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        # Return a simple sitemap with one url
        content = b"""
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://a/</loc><lastmod>2024-01-01T00:00:00Z</lastmod></url>
        </urlset>
        """
        return FakeResponse(content=content)


class FakeSettings:
    def __init__(self):
        self.max_crawl_pages = 10
        self.max_concurrent_requests = 3
        self.default_sync_interval_days = 7
        self.max_sync_interval_days = 30
        self.enable_crawler = True
        self.markdown_url_suffix = ""
        self.crawler_lock_ttl_seconds = 300
        self.crawler_playwright_first = False
        self.crawler_min_concurrency = 1
        self.crawler_max_concurrency = 5
        self.crawler_max_sessions = 10

    def should_process_url(self, url: str) -> bool:
        return True

    def get_url_blacklist_prefixes(self):
        return ["https://bad.example/"]

    def get_random_user_agent(self):
        return "fake-agent/1.0"


class DummyDocuments:
    def __init__(self, docs):
        self._docs = docs

    async def list(self, limit=100000):
        return self._docs

    async def delete(self, url):
        # simulate deletion by removing matching doc
        self._docs = [d for d in self._docs if d.url.value != url]

    async def count(self):
        return len(self._docs)


class DummyUoW:
    def __init__(self, docs):
        self.documents = DummyDocuments(docs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        return True


class DummyDoc:
    def __init__(self, url):
        class U:
            def __init__(self, value):
                self.value = value

        self.url = U(url)


class FakeMetadataStore:
    def __init__(self):
        self._store = {}

    async def load_url_metadata(self, url):
        return self._store.get(url)

    async def save_url_metadata(self, payload):
        self._store[payload.get("url")] = payload

    async def list_all_metadata(self):
        return list(self._store.values())

    async def get_last_sync_time(self):
        return None

    async def save_last_sync_time(self, t):
        self._last = t

    def ensure_ready(self):
        return True

    async def cleanup_legacy_artifacts(self):
        return None

    async def get_sitemap_snapshot(self, _id):
        return None

    async def save_sitemap_snapshot(self, snapshot, _id=None):
        self._snap = snapshot

    async def try_acquire_lock(self, lock_id, owner, ttl_seconds):
        expires = datetime.now(timezone.utc)
        # Return a fake LockLease with all required attributes
        lease = type(
            "LockLease",
            (),
            {
                "lock_id": lock_id,
                "lease_id": "lease1",
                "expires_at": expires,
                "owner": owner,
            },
        )()
        return (lease, None)

    async def release_lock(self, lease):
        pass


class FakeProgressStore:
    async def save(self, progress):
        return None

    async def save_checkpoint(self, tenant, payload, keep_history=False):
        return None

    async def get_latest_for_tenant(self, tenant):
        return None


@pytest.mark.asyncio
async def test_calculate_next_due_various():
    settings = FakeSettings()
    metadata = FakeMetadataStore()
    progress = FakeProgressStore()

    SyncScheduler, SyncSchedulerConfig = get_scheduler_classes()
    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=lambda: DummyUoW([]),
        cache_service_factory=lambda: None,
        metadata_store=metadata,
        progress_store=progress,
        tenant_codename="x",
        config=SyncSchedulerConfig(entry_urls=["https://example.com/"], sitemap_urls=None),
    )

    now = datetime.now(timezone.utc)

    # recent: 1 day ago -> next due ~1 day
    recent = now - timedelta(days=1)
    nd = scheduler._calculate_next_due(recent)
    assert (nd - now).days == 1

    # moderate: 10 days ago -> next due default_sync_interval_days (7 days)
    moderate = now - timedelta(days=10)
    nd = scheduler._calculate_next_due(moderate)
    assert (nd - now).days == settings.default_sync_interval_days

    # old: 40 days ago -> next due max_sync_interval_days (30 days)
    old = now - timedelta(days=40)
    nd = scheduler._calculate_next_due(old)
    assert (nd - now).days == settings.max_sync_interval_days

    # no lastmod -> default
    nd = scheduler._calculate_next_due(None)
    assert (nd - now).days == settings.default_sync_interval_days


@pytest.mark.asyncio
async def test_mark_url_failed_backoff_and_save():
    settings = FakeSettings()
    metadata = FakeMetadataStore()
    progress = FakeProgressStore()

    SyncScheduler, SyncSchedulerConfig = get_scheduler_classes()
    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=lambda: DummyUoW([]),
        cache_service_factory=lambda: None,
        metadata_store=metadata,
        progress_store=progress,
        tenant_codename="t",
        config=SyncSchedulerConfig(entry_urls=["https://a/"], sitemap_urls=None),
    )

    # First failure
    await scheduler._mark_url_failed("https://a/page1", reason="NetErr")
    payload = metadata._store.get("https://a/page1")
    assert payload is not None
    assert payload["retry_count"] == 1

    # Second failure increases retry_count and backoff
    await scheduler._mark_url_failed("https://a/page1", reason="NetErr")
    payload2 = metadata._store.get("https://a/page1")
    assert payload2["retry_count"] == 2
    # next_due_at should be in the future
    assert datetime.fromisoformat(payload2["next_due_at"]) > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_apply_crawler_if_needed_branches():
    settings = FakeSettings()
    metadata = FakeMetadataStore()
    progress = FakeProgressStore()

    # Helper scheduler factory
    def make_scheduler():
        SyncScheduler, SyncSchedulerConfig = get_scheduler_classes()
        return SyncScheduler(
            settings=settings,
            uow_factory=lambda: DummyUoW([]),
            cache_service_factory=lambda: None,
            metadata_store=metadata,
            progress_store=progress,
            tenant_codename="t",
            config=SyncSchedulerConfig(entry_urls=["https://root/"], sitemap_urls=None),
        )

    # Case: crawler disabled
    s1 = make_scheduler()
    s1.settings.enable_crawler = False
    got = await s1._apply_crawler_if_needed({"https://root/"}, sitemap_changed=False, force_crawler=False)
    assert got == {"https://root/"}

    # Case: should_run_crawler False due to has_previous_metadata and es_cached > filtered_count
    s2 = make_scheduler()
    s2.settings.enable_crawler = True

    async def has_prev():
        return True

    s2._has_previous_metadata = has_prev
    s2.stats.es_cached_count = 100
    s2.stats.filtered_urls = 1
    got = await s2._apply_crawler_if_needed({"https://root/"}, sitemap_changed=False, force_crawler=False)
    assert got == {"https://root/"}

    # Case: should_run_crawler True -> calls _crawl_links_from_roots
    # Create a scheduler in sitemap mode so crawler logic executes
    SyncScheduler, SyncSchedulerConfig = get_scheduler_classes()
    s3 = SyncScheduler(
        settings=settings,
        uow_factory=lambda: DummyUoW([]),
        cache_service_factory=lambda: None,
        metadata_store=metadata,
        progress_store=progress,
        tenant_codename="t",
        config=SyncSchedulerConfig(entry_urls=None, sitemap_urls=["https://root/"]),
    )

    s3._has_previous_metadata = lambda: asyncio.sleep(0, result=False)

    async def fake_crawl(root_urls, force_crawl=False):
        return {"https://root/page2"}

    s3._crawl_links_from_roots = fake_crawl
    # Ensure stats make crawler decide to run (es_cached_count <= filtered_urls)
    s3.stats.es_cached_count = 0
    s3.stats.filtered_urls = 10
    result = await s3._apply_crawler_if_needed({"https://root/"}, sitemap_changed=True, force_crawler=False)
    assert "https://root/page2" in result
    assert s3.stats.urls_discovered == 1


@pytest.mark.asyncio
async def test_crawl_links_from_roots_and_fetch_sitemap(monkeypatch):
    settings = FakeSettings()
    metadata = FakeMetadataStore()
    progress = FakeProgressStore()

    SyncScheduler, SyncSchedulerConfig = get_scheduler_classes()

    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=lambda: DummyUoW([]),
        cache_service_factory=lambda: None,
        metadata_store=metadata,
        progress_store=progress,
        tenant_codename="z",
        config=SyncSchedulerConfig(entry_urls=None, sitemap_urls=["https://sitemap.example/s.xml"]),
    )

    # Monkeypatch EfficientCrawler used in SyncDiscoveryRunner
    monkeypatch.setattr(
        "docs_mcp_server.utils.sync_discovery_runner.EfficientCrawler",
        FakeCrawler,
    )

    crawled = await scheduler._crawl_links_from_roots({"https://root/"}, force_crawl=False)
    assert "https://root/page1" in crawled

    # Monkeypatch httpx.AsyncClient used in _fetch_and_check_sitemap
    monkeypatch.setattr("docs_mcp_server.utils.sync_scheduler.httpx.AsyncClient", FakeAsyncClient)

    changed, entries = await scheduler._fetch_and_check_sitemap()
    assert isinstance(changed, bool)
    assert isinstance(entries, list)


@pytest.mark.asyncio
async def test_process_url_skip_and_success():
    settings = FakeSettings()
    metadata = FakeMetadataStore()
    progress = FakeProgressStore()

    SyncScheduler, SyncSchedulerConfig = get_scheduler_classes()

    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=lambda: DummyUoW([]),
        cache_service_factory=lambda: None,
        metadata_store=metadata,
        progress_store=progress,
        tenant_codename="u",
        config=SyncSchedulerConfig(entry_urls=["https://root/"], sitemap_urls=None),
    )

    # Prepare metadata that indicates recent successful fetch -> should skip
    now = datetime.now(timezone.utc)
    metadata._store["https://root/recent"] = {
        "url": "https://root/recent",
        "last_fetched_at": (now - timedelta(hours=1)).isoformat(),
        "next_due_at": (now + timedelta(days=1)).isoformat(),
        "last_status": "success",
        "retry_count": 0,
        "discovered_from": None,
        "first_seen_at": now.isoformat(),
    }

    # Fake cache service should not be called for skip; provide one that would raise if called
    class BrokenCacheService:
        async def check_and_fetch_page(self, url, **kwargs):
            raise RuntimeError("Should not be called")

    scheduler.cache_service_factory = lambda: BrokenCacheService()

    await scheduler._process_url("https://root/recent")
    assert scheduler.stats.urls_skipped >= 1

    # Now test success path
    # Clear any previous
    metadata = FakeMetadataStore()
    progress = FakeProgressStore()
    scheduler.metadata_store = metadata

    class GoodCacheService:
        async def check_and_fetch_page(self, url, **kwargs):
            return ("<html></html>", False, None)

    scheduler.cache_service_factory = lambda: GoodCacheService()

    await scheduler._process_url("https://root/newpage")
    saved = metadata._store.get("https://root/newpage")
    assert saved is not None
    assert saved.get("last_status") == "success"


@pytest.mark.asyncio
async def test_delete_blacklisted_caches_deletes_and_commits():
    settings = FakeSettings()
    metadata = FakeMetadataStore()
    progress = FakeProgressStore()

    # Create one doc that matches blacklist prefix
    docs = [DummyDoc("https://bad.example/page1"), DummyDoc("https://ok.example/page2")]

    def uow_factory():
        return DummyUoW(docs)

    SyncScheduler, SyncSchedulerConfig = get_scheduler_classes()
    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=uow_factory,
        cache_service_factory=lambda: None,
        metadata_store=metadata,
        progress_store=progress,
        tenant_codename="z",
        config=SyncSchedulerConfig(entry_urls=["https://root/"], sitemap_urls=None),
    )

    stats = await scheduler.delete_blacklisted_caches()
    assert stats["deleted"] == 1
    assert stats["checked"] >= 1
