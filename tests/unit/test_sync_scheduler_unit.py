"""Unit tests for SyncScheduler and SyncMetadata.

Tests the synchronization scheduler logic, metadata tracking, and cron parsing.

Note: Due to circular import issues in the codebase, we use deferred imports
within test methods to avoid import-time errors.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import logging
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from docs_mcp_server.utils.sync_metadata_store import LockLease


pytestmark = pytest.mark.unit


def _import_sync_scheduler():
    """Import SyncScheduler module avoiding circular imports.

    This function handles the import inside try/except to work around
    circular import issues during first import.
    """
    try:
        from docs_mcp_server.utils import sync_scheduler

        return sync_scheduler
    except ImportError:
        # Force import by going through config first
        from docs_mcp_server import config  # noqa: F401
        from docs_mcp_server.utils import sync_scheduler

        return sync_scheduler


def _progress_store_stub():
    """Create a stubbed progress store with async methods."""

    store = MagicMock()
    store.get_latest_for_tenant = AsyncMock(return_value=None)
    store.save = AsyncMock()
    store.save_checkpoint = AsyncMock()
    return store


def _build_scheduler_config(kwargs: dict, module=None):
    """Construct a SyncSchedulerConfig from keyword arguments."""

    sync_scheduler = module or _import_sync_scheduler()
    config_class = sync_scheduler.SyncSchedulerConfig

    existing = kwargs.pop("config", None)
    if existing is not None:
        return existing

    config_kwargs: dict[str, object] = {}
    for key in ("sitemap_urls", "entry_urls", "refresh_schedule"):
        if key in kwargs:
            config_kwargs[key] = kwargs.pop(key)

    return config_class(**config_kwargs)


class _InMemoryMetadataStore:
    """Simple async metadata store backed by dict for scheduler tests."""

    def __init__(self, root: Path):
        self.metadata_root = root
        self.metadata_root.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict] = {}
        self._last_sync_time: datetime | None = None
        self._snapshots: dict[str, dict] = {}
        self._debug_snapshots: dict[str, dict] = {}
        self._locks: dict[str, LockLease] = {}

    async def load_url_metadata(self, url: str) -> dict | None:
        return self._data.get(url)

    async def save_url_metadata(self, payload: dict) -> None:
        self._data[payload["url"]] = payload

    async def list_all_metadata(self) -> list[dict]:
        return list(self._data.values())

    async def get_last_sync_time(self) -> datetime | None:
        return self._last_sync_time

    async def save_last_sync_time(self, sync_time: datetime) -> None:
        self._last_sync_time = sync_time

    def ensure_ready(self) -> None:
        return None

    async def cleanup_legacy_artifacts(self) -> None:
        return None

    async def get_sitemap_snapshot(self, snapshot_id: str) -> dict | None:
        return self._snapshots.get(snapshot_id)

    async def save_sitemap_snapshot(self, snapshot: dict, snapshot_id: str) -> None:
        self._snapshots[snapshot_id] = snapshot

    async def save_debug_snapshot(self, name: str, payload: dict) -> None:
        self._debug_snapshots[name] = payload

    async def try_acquire_lock(
        self, name: str, owner: str, ttl_seconds: int
    ) -> tuple[LockLease | None, LockLease | None]:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl_seconds)
        existing = self._locks.get(name)
        if existing and not existing.is_expired(now=now):
            return None, existing

        lease = LockLease(
            name=name, owner=owner, acquired_at=now, expires_at=expires, path=self.metadata_root / f"{name}.lock"
        )
        self._locks[name] = lease
        return lease, existing

    async def release_lock(self, lease: LockLease) -> None:
        current = self._locks.get(lease.name)
        if current and current.owner == lease.owner:
            self._locks.pop(lease.name, None)

    async def break_lock(self, name: str) -> None:
        self._locks.pop(name, None)


class _DummySettings:
    """Minimal settings stub covering scheduler helpers."""

    def __init__(self, *, blacklist_prefixes: list[str] | None = None):
        self.default_sync_interval_days = 7
        self.max_sync_interval_days = 30
        self.enable_crawler = True
        self.max_crawl_pages = 50
        self.max_concurrent_requests = 5
        self._blacklist_prefixes = blacklist_prefixes or []
        self.markdown_url_suffix = ""
        self.crawler_lock_ttl_seconds = 180
        self.crawler_min_concurrency = 5
        self.crawler_max_concurrency = 10
        self.crawler_max_sessions = 100

    def should_process_url(self, url: str) -> bool:
        return not url.startswith("skip")

    def get_random_user_agent(self) -> str:
        return "unit-test-agent"

    def get_url_blacklist_prefixes(self) -> list[str]:
        return list(self._blacklist_prefixes)


class _FakeCacheService:
    """Simple cache service stub returning a preconfigured response."""

    def __init__(self, result):
        if isinstance(result, tuple) and len(result) == 2:
            page, cached = result
            self._result = (page, cached, None)
        else:
            self._result = result
        self.calls: list[str] = []

    async def check_and_fetch_page(self, url: str, **kwargs):
        self.calls.append(url)
        return self._result


class _FakeDocument:
    def __init__(self, url: str):
        self.url = SimpleNamespace(value=url)


class _FakeDocumentRepository:
    """In-memory document repository for blacklist cleanup tests."""

    def __init__(self, urls: list[str]):
        self._docs = [_FakeDocument(url) for url in urls]
        self.deleted: list[str] = []

    async def list(self, limit: int):
        return list(self._docs)

    async def delete(self, url: str):
        self.deleted.append(url)
        self._docs = [doc for doc in self._docs if doc.url.value != url]

    async def get(self, url: str):
        return next((doc for doc in self._docs if doc.url.value == url), None)

    async def count(self):
        return len(self._docs)


class _FakeUnitOfWork:
    """Async context manager implementing the unit-of-work protocol."""

    def __init__(self, repo: _FakeDocumentRepository):
        self.documents = repo
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        self.committed = True


def _create_scheduler_with_in_memory_store(
    tmp_path: Path, *, settings: _DummySettings | None = None, config_kwargs: dict | None = None
):
    """Factory producing a scheduler backed by in-memory metadata."""

    sync_scheduler = _import_sync_scheduler()
    sync_scheduler_cls = sync_scheduler.SyncScheduler
    sync_scheduler_config_cls = sync_scheduler.SyncSchedulerConfig

    metadata_store = _InMemoryMetadataStore(tmp_path)
    config_data = dict(config_kwargs or {})
    if "sitemap_urls" not in config_data and "entry_urls" not in config_data:
        config_data["sitemap_urls"] = ["https://example.com/sitemap.xml"]
    scheduler = sync_scheduler_cls(
        settings=settings or _DummySettings(),
        uow_factory=MagicMock(),
        cache_service_factory=MagicMock(),
        metadata_store=metadata_store,
        progress_store=_progress_store_stub(),
        tenant_codename="test-tenant",
        config=sync_scheduler_config_cls(**config_data),
    )
    return scheduler, metadata_store


class _FakeAsyncHTTPClient:
    """Minimal async HTTPX client stub for redirect resolution tests."""

    def __init__(
        self,
        responses: dict[str, str],
        errors: set[str] | None = None,
        delay_seconds: float = 0.0,
    ):
        self._responses = responses
        self._errors = errors or set()
        self._delay_seconds = delay_seconds

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def head(self, url: str):
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        if url in self._errors:
            raise httpx.HTTPError("boom")
        final_url = self._responses.get(url, url)
        return SimpleNamespace(url=final_url)


@pytest.mark.unit
class TestSyncMetadata:
    """Tests for SyncMetadata data class."""

    def test_init_with_minimal_args(self):
        """Test initialization with only required argument."""
        sync_scheduler = _import_sync_scheduler()
        sync_metadata_cls = sync_scheduler.SyncMetadata

        metadata = sync_metadata_cls(url="https://example.com/page")
        assert metadata.url == "https://example.com/page"
        assert metadata.discovered_from is None
        assert metadata.last_fetched_at is None
        assert metadata.last_status == "pending"
        assert metadata.retry_count == 0
        assert metadata.first_seen_at is not None
        assert metadata.next_due_at is not None

    def test_init_with_all_args(self):
        """Test initialization with all arguments."""
        from docs_mcp_server.utils.sync_scheduler import SyncMetadata

        now = datetime.now(timezone.utc)
        metadata = SyncMetadata(
            url="https://example.com/page",
            discovered_from="https://example.com/sitemap.xml",
            first_seen_at=now,
            last_fetched_at=now,
            next_due_at=now + timedelta(days=1),
            last_status="success",
            retry_count=3,
        )
        assert metadata.url == "https://example.com/page"
        assert metadata.discovered_from == "https://example.com/sitemap.xml"
        assert metadata.first_seen_at == now
        assert metadata.last_fetched_at == now
        assert metadata.next_due_at == now + timedelta(days=1)
        assert metadata.last_status == "success"
        assert metadata.retry_count == 3

    def test_to_dict(self):
        """Test conversion to dictionary."""
        from docs_mcp_server.utils.sync_scheduler import SyncMetadata

        now = datetime.now(timezone.utc)
        metadata = SyncMetadata(
            url="https://example.com/page",
            discovered_from="sitemap",
            first_seen_at=now,
            last_fetched_at=now,
            next_due_at=now + timedelta(days=1),
            last_status="success",
            retry_count=2,
        )
        result = metadata.to_dict()

        assert result["url"] == "https://example.com/page"
        assert result["discovered_from"] == "sitemap"
        assert result["first_seen_at"] == now.isoformat()
        assert result["last_fetched_at"] == now.isoformat()
        assert result["next_due_at"] == (now + timedelta(days=1)).isoformat()
        assert result["last_status"] == "success"
        assert result["retry_count"] == 2

    def test_to_dict_with_none_last_fetched(self):
        """Test to_dict when last_fetched_at is None."""
        from docs_mcp_server.utils.sync_scheduler import SyncMetadata

        metadata = SyncMetadata(url="https://example.com/page")
        result = metadata.to_dict()
        assert result["last_fetched_at"] is None

    def test_from_dict(self):
        """Test reconstruction from dictionary."""
        from docs_mcp_server.utils.sync_scheduler import SyncMetadata

        now = datetime.now(timezone.utc)
        data = {
            "url": "https://example.com/page",
            "discovered_from": "crawler",
            "first_seen_at": now.isoformat(),
            "last_fetched_at": now.isoformat(),
            "next_due_at": (now + timedelta(days=7)).isoformat(),
            "last_status": "success",
            "retry_count": 1,
        }
        metadata = SyncMetadata.from_dict(data)

        assert metadata.url == "https://example.com/page"
        assert metadata.discovered_from == "crawler"
        assert metadata.first_seen_at == now
        assert metadata.last_fetched_at == now
        assert metadata.next_due_at == now + timedelta(days=7)
        assert metadata.last_status == "success"
        assert metadata.retry_count == 1

    def test_from_dict_with_none_last_fetched(self):
        """Test from_dict when last_fetched_at is None."""
        from docs_mcp_server.utils.sync_scheduler import SyncMetadata

        now = datetime.now(timezone.utc)
        data = {
            "url": "https://example.com/page",
            "first_seen_at": now.isoformat(),
            "last_fetched_at": None,
            "next_due_at": now.isoformat(),
        }
        metadata = SyncMetadata.from_dict(data)
        assert metadata.last_fetched_at is None

    def test_from_dict_with_missing_optional_fields(self):
        """Test from_dict with missing optional fields uses defaults."""
        from docs_mcp_server.utils.sync_scheduler import SyncMetadata

        now = datetime.now(timezone.utc)
        data = {
            "url": "https://example.com/page",
            "first_seen_at": now.isoformat(),
            "next_due_at": now.isoformat(),
        }
        metadata = SyncMetadata.from_dict(data)
        assert metadata.discovered_from is None
        assert metadata.last_status == "pending"
        assert metadata.retry_count == 0

    def test_roundtrip_serialization(self):
        """Test that to_dict and from_dict are inverses."""
        from docs_mcp_server.utils.sync_scheduler import SyncMetadata

        now = datetime.now(timezone.utc)
        original = SyncMetadata(
            url="https://example.com/test",
            discovered_from="sitemap",
            first_seen_at=now,
            last_fetched_at=now - timedelta(hours=1),
            next_due_at=now + timedelta(days=7),
            last_status="success",
            retry_count=5,
        )
        serialized = original.to_dict()
        restored = SyncMetadata.from_dict(serialized)

        assert restored.url == original.url
        assert restored.discovered_from == original.discovered_from
        assert restored.first_seen_at == original.first_seen_at
        assert restored.last_fetched_at == original.last_fetched_at
        assert restored.next_due_at == original.next_due_at
        assert restored.last_status == original.last_status
        assert restored.retry_count == original.retry_count


@pytest.mark.unit
class TestSyncSchedulerInit:
    """Tests for SyncScheduler initialization."""

    def _create_scheduler(self, **kwargs):
        """Helper to create scheduler with mocked dependencies."""
        module = _import_sync_scheduler()
        sync_scheduler_cls = module.SyncScheduler

        mock_settings = MagicMock()
        mock_settings.default_sync_interval_days = 7
        mock_settings.max_sync_interval_days = 30

        progress_store = _progress_store_stub()
        config = _build_scheduler_config(kwargs, module)

        defaults = {
            "settings": mock_settings,
            "uow_factory": MagicMock(),
            "cache_service_factory": MagicMock(),
            "metadata_store": MagicMock(),
            "progress_store": progress_store,
            "tenant_codename": "test-tenant",
            "config": config,
        }
        defaults.update(kwargs)
        return sync_scheduler_cls(**defaults)

    def test_init_with_sitemap_urls(self):
        """Test initialization with sitemap URLs."""
        scheduler = self._create_scheduler(sitemap_urls=["https://example.com/sitemap.xml"])
        assert scheduler.sitemap_urls == ["https://example.com/sitemap.xml"]
        assert scheduler.entry_urls == []
        assert scheduler.mode == "sitemap"

    def test_init_with_entry_urls(self):
        """Test initialization with entry URLs."""
        scheduler = self._create_scheduler(entry_urls=["https://example.com/docs/"])
        assert scheduler.sitemap_urls == []
        assert scheduler.entry_urls == ["https://example.com/docs/"]
        assert scheduler.mode == "entry"

    def test_init_with_both_urls_hybrid_mode(self):
        """Test initialization with both URL types creates hybrid mode."""
        scheduler = self._create_scheduler(
            sitemap_urls=["https://example.com/sitemap.xml"],
            entry_urls=["https://example.com/docs/"],
        )
        assert scheduler.mode == "hybrid"

    def test_init_without_urls_raises_error(self):
        """Test that init without any URLs raises ValueError."""
        from docs_mcp_server.utils.sync_scheduler import SyncScheduler

        mock_settings = MagicMock()
        mock_settings.default_sync_interval_days = 7
        mock_settings.max_sync_interval_days = 30

        progress_store = _progress_store_stub()

        with pytest.raises(ValueError, match="At least one of sitemap_urls or entry_urls"):
            SyncScheduler(
                settings=mock_settings,
                uow_factory=MagicMock(),
                cache_service_factory=MagicMock(),
                metadata_store=MagicMock(),
                progress_store=progress_store,
                tenant_codename="test-tenant",
            )

    def test_init_with_valid_cron_schedule(self):
        """Test initialization with valid cron schedule."""
        scheduler = self._create_scheduler(
            sitemap_urls=["https://example.com/sitemap.xml"],
            refresh_schedule="0 2 * * 1",  # Every Monday at 2 AM
        )
        assert scheduler.refresh_schedule == "0 2 * * 1"
        assert scheduler.cron_instance is not None

    def test_init_with_invalid_cron_schedule(self):
        """Test that invalid cron schedule raises ValueError."""
        with pytest.raises(ValueError, match="Invalid cron schedule"):
            self._create_scheduler(
                sitemap_urls=["https://example.com/sitemap.xml"],
                refresh_schedule="invalid cron",
            )

    def test_init_without_schedule(self):
        """Test initialization without refresh schedule."""
        scheduler = self._create_scheduler(
            sitemap_urls=["https://example.com/sitemap.xml"],
            refresh_schedule=None,
        )
        assert scheduler.refresh_schedule is None
        assert scheduler.cron_instance is None

    def test_init_stats_initialized(self):
        """Test that stats dictionary is properly initialized."""
        scheduler = self._create_scheduler(sitemap_urls=["https://example.com/sitemap.xml"])
        assert scheduler.stats["total_syncs"] == 0
        assert scheduler.stats["urls_processed"] == 0
        assert scheduler.stats["errors"] == 0
        assert scheduler.stats["mode"] == "sitemap"


@pytest.mark.unit
class TestSyncSchedulerDetermineMode:
    """Tests for _determine_mode method."""

    def _create_scheduler(self, **kwargs):
        """Helper to create scheduler with mocked dependencies."""
        module = _import_sync_scheduler()
        sync_scheduler_cls = module.SyncScheduler

        mock_settings = MagicMock()
        mock_settings.default_sync_interval_days = 7
        mock_settings.max_sync_interval_days = 30

        if "sitemap_urls" not in kwargs and "entry_urls" not in kwargs:
            kwargs["sitemap_urls"] = ["https://example.com/sitemap.xml"]
        config = _build_scheduler_config(kwargs, module)

        defaults = {
            "settings": mock_settings,
            "uow_factory": MagicMock(),
            "cache_service_factory": MagicMock(),
            "metadata_store": MagicMock(),
            "progress_store": _progress_store_stub(),
            "tenant_codename": "test-tenant",
            "config": config,
        }
        defaults.update(kwargs)
        return sync_scheduler_cls(**defaults)

    def test_sitemap_only_mode(self):
        """Test sitemap mode when only sitemap URLs provided."""
        scheduler = self._create_scheduler(sitemap_urls=["https://example.com/sitemap.xml"])
        assert scheduler._determine_mode() == "sitemap"

    def test_entry_only_mode(self):
        """Test entry mode when only entry URLs provided."""
        scheduler = self._create_scheduler(entry_urls=["https://example.com/docs/"])
        assert scheduler._determine_mode() == "entry"

    def test_hybrid_mode(self):
        """Test hybrid mode when both URL types provided."""
        scheduler = self._create_scheduler(
            sitemap_urls=["https://example.com/sitemap.xml"],
            entry_urls=["https://example.com/docs/"],
        )
        assert scheduler._determine_mode() == "hybrid"


@pytest.mark.unit
class TestSyncSchedulerCalculateScheduleInterval:
    """Tests for _calculate_schedule_interval_hours method."""

    def _create_scheduler(self, **kwargs):
        """Helper to create scheduler with mocked dependencies."""
        module = _import_sync_scheduler()
        sync_scheduler_cls = module.SyncScheduler

        mock_settings = MagicMock()
        mock_settings.default_sync_interval_days = 7
        mock_settings.max_sync_interval_days = 30

        if "sitemap_urls" not in kwargs and "entry_urls" not in kwargs:
            kwargs["sitemap_urls"] = ["https://example.com/sitemap.xml"]
        config = _build_scheduler_config(kwargs, module)

        defaults = {
            "settings": mock_settings,
            "uow_factory": MagicMock(),
            "cache_service_factory": MagicMock(),
            "metadata_store": MagicMock(),
            "progress_store": _progress_store_stub(),
            "tenant_codename": "test-tenant",
            "config": config,
        }
        defaults.update(kwargs)
        return sync_scheduler_cls(**defaults)

    def test_no_cron_schedule_returns_default(self):
        """Test that no cron schedule returns 24 hour default."""
        scheduler = self._create_scheduler(
            sitemap_urls=["https://example.com/sitemap.xml"],
            refresh_schedule=None,
        )
        assert scheduler.schedule_interval_hours == 24.0

    def test_weekly_cron_schedule(self):
        """Test weekly cron schedule returns ~168 hours."""
        scheduler = self._create_scheduler(
            sitemap_urls=["https://example.com/sitemap.xml"],
            refresh_schedule="0 2 * * 1",  # Every Monday at 2 AM
        )
        # Weekly = 168 hours
        assert scheduler.schedule_interval_hours == pytest.approx(168.0, rel=0.1)

    def test_daily_cron_schedule(self):
        """Test daily cron schedule returns 24 hours."""
        scheduler = self._create_scheduler(
            sitemap_urls=["https://example.com/sitemap.xml"],
            refresh_schedule="0 2 * * *",  # Every day at 2 AM
        )
        assert scheduler.schedule_interval_hours == pytest.approx(24.0, rel=0.1)

    def test_schedule_interval_enforces_minimum_one_hour(self):
        """Intervals shorter than an hour are floored to 1.0."""
        scheduler = self._create_scheduler(refresh_schedule=None)
        now = datetime.now(timezone.utc)

        class _SubHourlyCron:
            def __init__(self, reference):
                self.reference = reference
                self.calls = 0

            def schedule(self, *_args, **_kwargs):
                return self

            def next(self):
                self.calls += 1
                if self.calls == 1:
                    return self.reference
                return self.reference + timedelta(minutes=30)

        scheduler.cron_instance = _SubHourlyCron(now)
        assert scheduler._calculate_schedule_interval_hours() == pytest.approx(1.0, rel=1e-3)

    def test_schedule_interval_handles_cron_errors(self):
        """Cron schedule failures fall back to the 24h default."""
        scheduler = self._create_scheduler(refresh_schedule=None)

        class _FailingCron:
            def schedule(self, *_args, **_kwargs):
                return self

            def next(self):
                raise RuntimeError("boom")

        scheduler.cron_instance = _FailingCron()
        assert scheduler._calculate_schedule_interval_hours() == 24.0

    def test_hourly_cron_schedule_enforces_minimum(self):
        """Test that more frequent schedules enforce 1 hour minimum."""
        scheduler = self._create_scheduler(
            sitemap_urls=["https://example.com/sitemap.xml"],
            refresh_schedule="0 * * * *",  # Every hour
        )
        # Should enforce minimum 1 hour
        assert scheduler.schedule_interval_hours >= 1.0


@pytest.mark.unit
class TestSyncSchedulerCalculateNextDue:
    """Tests for _calculate_next_due method."""

    def _create_scheduler(self, **kwargs):
        """Helper to create scheduler with mocked dependencies."""
        module = _import_sync_scheduler()
        sync_scheduler_cls = module.SyncScheduler

        mock_settings = MagicMock()
        mock_settings.default_sync_interval_days = 7
        mock_settings.max_sync_interval_days = 30

        if "sitemap_urls" not in kwargs and "entry_urls" not in kwargs:
            kwargs["sitemap_urls"] = ["https://example.com/sitemap.xml"]
        config = _build_scheduler_config(kwargs, module)

        defaults = {
            "settings": mock_settings,
            "uow_factory": MagicMock(),
            "cache_service_factory": MagicMock(),
            "metadata_store": MagicMock(),
            "progress_store": _progress_store_stub(),
            "tenant_codename": "test-tenant",
            "config": config,
        }
        defaults.update(kwargs)
        return sync_scheduler_cls(**defaults)

    def test_no_lastmod_returns_default_interval(self):
        """Test that no lastmod uses default 7-day interval."""
        scheduler = self._create_scheduler()
        now = datetime.now(timezone.utc)
        next_due = scheduler._calculate_next_due(sitemap_lastmod=None)

        # Should be approximately 7 days from now
        expected = now + timedelta(days=7)
        assert abs((next_due - expected).total_seconds()) < 2

    def test_recent_lastmod_returns_1_day(self):
        """Test recent modification (< 7 days) schedules 1 day check."""
        scheduler = self._create_scheduler()
        now = datetime.now(timezone.utc)
        recent_mod = now - timedelta(days=3)
        next_due = scheduler._calculate_next_due(sitemap_lastmod=recent_mod)

        # Should be approximately 1 day from now
        expected = now + timedelta(days=1)
        assert abs((next_due - expected).total_seconds()) < 2

    def test_moderate_lastmod_returns_7_days(self):
        """Test moderate modification (7-30 days) schedules 7 day check."""
        scheduler = self._create_scheduler()
        now = datetime.now(timezone.utc)
        moderate_mod = now - timedelta(days=15)
        next_due = scheduler._calculate_next_due(sitemap_lastmod=moderate_mod)

        # Should be approximately 7 days from now
        expected = now + timedelta(days=7)
        assert abs((next_due - expected).total_seconds()) < 2

    def test_old_lastmod_returns_30_days(self):
        """Test old modification (> 30 days) schedules 30 day check."""
        scheduler = self._create_scheduler()
        now = datetime.now(timezone.utc)
        old_mod = now - timedelta(days=60)
        next_due = scheduler._calculate_next_due(sitemap_lastmod=old_mod)

        # Should be approximately 30 days from now
        expected = now + timedelta(days=30)
        assert abs((next_due - expected).total_seconds()) < 2

    def test_naive_datetime_made_aware(self):
        """Test that naive datetime is made timezone-aware."""
        scheduler = self._create_scheduler()
        now = datetime.now(timezone.utc)
        # Create naive datetime (no timezone)
        naive_mod = (datetime.now(timezone.utc) - timedelta(days=3)).replace(tzinfo=None)
        next_due = scheduler._calculate_next_due(sitemap_lastmod=naive_mod)

        # Should not raise and should return valid datetime
        assert next_due > now

    def test_edge_case_exactly_7_days(self):
        """Test edge case of exactly 7 days old modification."""
        scheduler = self._create_scheduler()
        now = datetime.now(timezone.utc)
        boundary_mod = now - timedelta(days=7)
        next_due = scheduler._calculate_next_due(sitemap_lastmod=boundary_mod)

        # 7 days falls in "moderate" category (7-30), so should be 7 days
        expected = now + timedelta(days=7)
        assert abs((next_due - expected).total_seconds()) < 2

    def test_edge_case_exactly_30_days(self):
        """Test edge case of exactly 30 days old modification."""
        scheduler = self._create_scheduler()
        now = datetime.now(timezone.utc)
        boundary_mod = now - timedelta(days=30)
        next_due = scheduler._calculate_next_due(sitemap_lastmod=boundary_mod)

        # 30 days falls in "old" category (>30), so should be 30 days
        expected = now + timedelta(days=30)
        assert abs((next_due - expected).total_seconds()) < 2


@pytest.mark.unit
class TestSyncSchedulerExtractUrlsFromSitemap:
    """Tests for _extract_urls_from_sitemap method."""

    def _create_scheduler(self, **kwargs):
        """Helper to create scheduler with mocked dependencies."""
        module = _import_sync_scheduler()
        sync_scheduler_cls = module.SyncScheduler

        mock_settings = MagicMock()
        mock_settings.default_sync_interval_days = 7
        mock_settings.max_sync_interval_days = 30

        if "sitemap_urls" not in kwargs and "entry_urls" not in kwargs:
            kwargs["sitemap_urls"] = ["https://example.com/sitemap.xml"]
        config = _build_scheduler_config(kwargs, module)

        defaults = {
            "settings": mock_settings,
            "uow_factory": MagicMock(),
            "cache_service_factory": MagicMock(),
            "metadata_store": MagicMock(),
            "progress_store": _progress_store_stub(),
            "tenant_codename": "test-tenant",
            "config": config,
        }
        defaults.update(kwargs)
        return sync_scheduler_cls(**defaults)

    def test_empty_entries(self):
        """Test extraction from empty entry list."""
        scheduler = self._create_scheduler()
        urls, lastmod_map = scheduler._extract_urls_from_sitemap([])
        assert urls == set()
        assert lastmod_map == {}

    def test_entries_without_lastmod(self):
        """Test extraction when entries have no lastmod."""
        from docs_mcp_server.utils.models import SitemapEntry

        scheduler = self._create_scheduler()
        entries = [
            SitemapEntry(url="https://example.com/page1"),
            SitemapEntry(url="https://example.com/page2"),
        ]
        urls, lastmod_map = scheduler._extract_urls_from_sitemap(entries)

        assert urls == {"https://example.com/page1", "https://example.com/page2"}
        assert lastmod_map == {}

    def test_entries_with_lastmod(self):
        """Test extraction when entries have lastmod."""
        from docs_mcp_server.utils.models import SitemapEntry

        scheduler = self._create_scheduler()
        now = datetime.now(timezone.utc)
        entries = [
            SitemapEntry(url="https://example.com/page1", lastmod=now),
            SitemapEntry(url="https://example.com/page2", lastmod=now - timedelta(days=1)),
        ]
        urls, lastmod_map = scheduler._extract_urls_from_sitemap(entries)

        assert urls == {"https://example.com/page1", "https://example.com/page2"}
        assert len(lastmod_map) == 2
        assert lastmod_map["https://example.com/page1"] == now

    def test_mixed_entries(self):
        """Test extraction with some entries having lastmod."""
        from docs_mcp_server.utils.models import SitemapEntry

        scheduler = self._create_scheduler()
        now = datetime.now(timezone.utc)
        entries = [
            SitemapEntry(url="https://example.com/page1", lastmod=now),
            SitemapEntry(url="https://example.com/page2"),  # No lastmod
            SitemapEntry(url="https://example.com/page3", lastmod=now - timedelta(days=5)),
        ]
        urls, lastmod_map = scheduler._extract_urls_from_sitemap(entries)

        assert len(urls) == 3
        assert len(lastmod_map) == 2  # Only 2 have lastmod
        assert "https://example.com/page2" not in lastmod_map

    def test_duplicate_urls_deduplicated(self):
        """Test that duplicate URLs are deduplicated."""
        from docs_mcp_server.utils.models import SitemapEntry

        scheduler = self._create_scheduler()
        entries = [
            SitemapEntry(url="https://example.com/page"),
            SitemapEntry(url="https://example.com/page"),
        ]
        urls, _ = scheduler._extract_urls_from_sitemap(entries)

        assert len(urls) == 1
        assert "https://example.com/page" in urls


@pytest.mark.unit
class TestSyncSchedulerStartStop:
    """Tests for start/stop lifecycle methods."""

    def _create_scheduler(self, **kwargs):
        """Helper to create scheduler with mocked dependencies."""
        module = _import_sync_scheduler()
        sync_scheduler_cls = module.SyncScheduler

        mock_settings = MagicMock()
        mock_settings.default_sync_interval_days = 7
        mock_settings.max_sync_interval_days = 30

        if "sitemap_urls" not in kwargs and "entry_urls" not in kwargs:
            kwargs["sitemap_urls"] = ["https://example.com/sitemap.xml"]
        config = _build_scheduler_config(kwargs, module)

        defaults = {
            "settings": mock_settings,
            "uow_factory": MagicMock(),
            "cache_service_factory": MagicMock(),
            "metadata_store": MagicMock(),
            "progress_store": _progress_store_stub(),
            "tenant_codename": "test-tenant",
            "config": config,
        }
        defaults.update(kwargs)
        return sync_scheduler_cls(**defaults)

    @pytest.mark.asyncio
    async def test_start_initializes_components(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler._ensure_metadata_can_be_accessed = AsyncMock()
        scheduler._load_sitemap_metadata = AsyncMock()
        scheduler._update_cache_stats = AsyncMock()

        created: list = []

        def fake_create_task(coro):
            created.append(coro)
            return AsyncMock()

        monkeypatch.setattr("docs_mcp_server.utils.sync_scheduler.asyncio.create_task", fake_create_task)

        await scheduler.start()

        assert scheduler.running
        scheduler._ensure_metadata_can_be_accessed.assert_awaited_once()
        scheduler._load_sitemap_metadata.assert_awaited_once()
        scheduler._update_cache_stats.assert_awaited_once()
        assert created, "expected a background task to be scheduled"

        scheduler.running = False


@pytest.mark.unit
class TestSyncSchedulerApplyCrawler:
    """Tests for _apply_crawler_if_needed logic."""

    def _create_scheduler(self, **kwargs):
        module = _import_sync_scheduler()
        sync_scheduler_cls = module.SyncScheduler

        mock_settings = MagicMock()
        mock_settings.default_sync_interval_days = 7
        mock_settings.max_sync_interval_days = 30
        mock_settings.enable_crawler = True

        if "sitemap_urls" not in kwargs and "entry_urls" not in kwargs:
            kwargs["sitemap_urls"] = ["https://example.com/sitemap.xml"]
        config = _build_scheduler_config(kwargs, module)

        defaults = {
            "settings": mock_settings,
            "uow_factory": MagicMock(),
            "cache_service_factory": MagicMock(),
            "metadata_store": MagicMock(),
            "progress_store": _progress_store_stub(),
            "tenant_codename": "test-tenant",
            "config": config,
        }
        defaults.update(kwargs)
        return sync_scheduler_cls(**defaults)

    @pytest.mark.asyncio
    async def test_entry_mode_returns_existing_urls(self):
        scheduler = self._create_scheduler(entry_urls=["https://example.com/docs/"])
        scheduler.mode = "entry"

        result = await scheduler._apply_crawler_if_needed({"https://root"}, sitemap_changed=False, force_crawler=False)

        assert result == {"https://root"}

    @pytest.mark.asyncio
    async def test_crawler_disabled_returns_existing_urls(self):
        scheduler = self._create_scheduler()
        scheduler.mode = "sitemap"
        scheduler.settings.enable_crawler = False

        result = await scheduler._apply_crawler_if_needed({"https://root"}, sitemap_changed=True, force_crawler=False)

        assert result == {"https://root"}

    @pytest.mark.asyncio
    async def test_crawler_skips_when_not_needed(self):
        scheduler = self._create_scheduler()
        scheduler.mode = "sitemap"
        scheduler.settings.enable_crawler = True
        scheduler._has_previous_metadata = AsyncMock(return_value=True)
        scheduler._crawl_links_from_roots = AsyncMock()
        scheduler.stats["es_cached_count"] = 10
        scheduler.stats["filtered_urls"] = 1

        result = await scheduler._apply_crawler_if_needed({"https://root"}, sitemap_changed=False, force_crawler=False)

        scheduler._crawl_links_from_roots.assert_not_called()
        assert result == {"https://root"}

    @pytest.mark.asyncio
    async def test_crawler_runs_when_forced(self):
        scheduler = self._create_scheduler()
        scheduler.mode = "sitemap"
        scheduler.settings.enable_crawler = True
        scheduler._has_previous_metadata = AsyncMock(return_value=False)
        scheduler._crawl_links_from_roots = AsyncMock(return_value={"https://extra"})

        result = await scheduler._apply_crawler_if_needed({"https://root"}, sitemap_changed=False, force_crawler=True)

        scheduler._crawl_links_from_roots.assert_awaited_once()
        assert result == {"https://root", "https://extra"}
        assert scheduler.stats["urls_discovered"] == 1
        assert scheduler.stats["crawler_total_runs"] == 1

    @pytest.mark.asyncio
    async def test_crawler_runs_when_cache_sparse(self, caplog):
        scheduler = self._create_scheduler()
        scheduler.mode = "sitemap"
        scheduler.settings.enable_crawler = True
        scheduler._has_previous_metadata = AsyncMock(return_value=True)
        scheduler._crawl_links_from_roots = AsyncMock(return_value={"https://extra"})
        scheduler.stats["es_cached_count"] = 0
        scheduler.stats["filtered_urls"] = 5
        scheduler.stats["storage_doc_count"] = 1

        with caplog.at_level(logging.INFO):
            result = await scheduler._apply_crawler_if_needed(
                {"https://root"}, sitemap_changed=False, force_crawler=False
            )

        scheduler._crawl_links_from_roots.assert_awaited_once()
        assert result == {"https://root", "https://extra"}
        assert "sparse cache" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_start_when_already_running(self):
        """Test start is no-op when already running."""
        scheduler = self._create_scheduler()
        scheduler.running = True
        # Mock internal methods to avoid actual execution
        scheduler._ensure_metadata_can_be_accessed = AsyncMock()
        scheduler._load_sitemap_metadata = AsyncMock()
        scheduler._update_cache_stats = AsyncMock()

        # Should warn and return without creating new task
        await scheduler.start()

        # Internal methods should not be called when already running
        scheduler._ensure_metadata_can_be_accessed.assert_not_called()


@pytest.mark.unit
class TestSyncSchedulerGetStats:
    """Tests for get_stats method."""

    def _create_scheduler(self, **kwargs):
        """Helper to create scheduler with mocked dependencies."""
        module = _import_sync_scheduler()
        sync_scheduler_cls = module.SyncScheduler

        mock_settings = MagicMock()
        mock_settings.default_sync_interval_days = 7
        mock_settings.max_sync_interval_days = 30

        if "sitemap_urls" not in kwargs and "entry_urls" not in kwargs:
            kwargs["sitemap_urls"] = ["https://example.com/sitemap.xml"]
        config = _build_scheduler_config(kwargs, module)

        defaults = {
            "settings": mock_settings,
            "uow_factory": MagicMock(),
            "cache_service_factory": MagicMock(),
            "metadata_store": MagicMock(),
            "progress_store": _progress_store_stub(),
            "tenant_codename": "test-tenant",
            "config": config,
        }
        defaults.update(kwargs)
        return sync_scheduler_cls(**defaults)

    def test_get_stats_returns_copy(self):
        """Test that get_stats returns stats dictionary."""
        scheduler = self._create_scheduler(
            sitemap_urls=["https://example.com/sitemap.xml"],
            refresh_schedule="0 2 * * 1",
        )
        stats = scheduler.get_stats()

        assert "mode" in stats
        assert "total_syncs" in stats
        assert "urls_processed" in stats
        assert "refresh_schedule" in stats
        assert stats["refresh_schedule"] == "0 2 * * 1"

    def test_stats_reflect_mode(self):
        """Test that stats reflect correct mode."""
        scheduler = self._create_scheduler(
            sitemap_urls=["https://example.com/sitemap.xml"],
            entry_urls=["https://example.com/docs/"],
        )
        stats = scheduler.get_stats()
        assert stats["mode"] == "hybrid"

    @pytest.mark.asyncio
    async def test_stats_include_sync_fields_and_progress_queue(self, tmp_path: Path):
        """Stats should surface last/next sync timestamps and queue depth."""
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        progress = await scheduler._load_or_create_progress()
        progress.start_discovery()
        progress.add_discovered_urls({"https://example.com/a", "https://example.com/b"})
        scheduler._active_progress = progress
        scheduler._update_queue_depth_from_progress()

        last_sync = datetime.now(timezone.utc).isoformat()
        next_sync = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        scheduler.stats["last_sync_at"] = last_sync
        scheduler.stats["next_sync_at"] = next_sync
        scheduler.stats["errors"] = 2

        stats = scheduler.get_stats()

        assert stats["last_sync_at"] == last_sync
        assert stats["next_sync_at"] == next_sync
        assert stats["queue_depth"] == 2
        assert stats["errors"] == 2

        # Ensure copy semantics so caller mutations don't leak back
        stats["errors"] = 99
        assert scheduler.stats["errors"] == 2


@pytest.mark.unit
class TestSyncSchedulerLifecycle:
    """Lifecycle helpers for the sync scheduler (start/stop/interval helpers)."""

    @pytest.mark.asyncio
    async def test_start_creates_task_and_loads_resources(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler._run_loop = AsyncMock()
        scheduler._ensure_metadata_can_be_accessed = AsyncMock()
        scheduler._load_sitemap_metadata = AsyncMock()
        scheduler._update_cache_stats = AsyncMock()

        created_tasks: list[object] = []
        task_stub = MagicMock()
        task_stub.cancel = MagicMock()

        def fake_create_task(coro):
            created_tasks.append(coro)
            return task_stub

        monkeypatch.setattr("docs_mcp_server.utils.sync_scheduler.asyncio.create_task", fake_create_task)

        await scheduler.start()

        scheduler._ensure_metadata_can_be_accessed.assert_awaited_once()
        scheduler._load_sitemap_metadata.assert_awaited_once()
        scheduler._update_cache_stats.assert_awaited_once()
        assert scheduler.running is True
        assert scheduler.task is task_stub
        assert created_tasks
        assert inspect.iscoroutine(created_tasks[0])
        task_stub.cancel.assert_not_called()

    def test_calculate_schedule_interval_hours_clamps_to_minimum(self, tmp_path: Path) -> None:
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)

        class _HalfHourCron:
            def __init__(self) -> None:
                self.start = None
                self.call_count = 0

            def schedule(self, start_date=None):
                self.start = start_date or datetime.now(timezone.utc)
                self.call_count = 0
                return self

            def next(self):
                self.call_count += 1
                return self.start + timedelta(minutes=30 * self.call_count)

        scheduler.cron_instance = _HalfHourCron()
        scheduler.refresh_schedule = "*/30 * * * *"

        interval = scheduler._calculate_schedule_interval_hours()
        assert interval == 1.0

    def test_calculate_schedule_interval_hours_handles_errors(self, tmp_path: Path) -> None:
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)

        class _BrokenCron:
            def schedule(self, *_args, **_kwargs):
                return self

            def next(self):
                raise RuntimeError("cron fail")

        scheduler.cron_instance = _BrokenCron()
        scheduler.refresh_schedule = "*/5 * * * *"

        assert scheduler._calculate_schedule_interval_hours() == 24.0


class TestSyncSchedulerMetadataOperations:
    """Exercises metadata scheduling helpers for better coverage."""

    def _create_scheduler(self, tmp_path: Path):
        return _create_scheduler_with_in_memory_store(tmp_path)

    @pytest.mark.asyncio
    async def test_update_metadata_overwrites_existing_values(self, tmp_path: Path):
        scheduler, metadata_store = self._create_scheduler(tmp_path)
        await metadata_store.save_url_metadata(
            {
                "url": "https://example.com/doc",
                "discovered_from": None,
                "first_seen_at": datetime.now(timezone.utc).isoformat(),
                "last_fetched_at": None,
                "next_due_at": datetime.now(timezone.utc).isoformat(),
                "last_status": "failed",
                "retry_count": 3,
            }
        )

        later = datetime.now(timezone.utc)
        next_due = later + timedelta(days=2)
        await scheduler._update_metadata(
            url="https://example.com/doc",
            last_fetched_at=later,
            next_due_at=next_due,
            status="success",
            retry_count=0,
        )

        updated = metadata_store._data["https://example.com/doc"]
        assert updated["last_status"] == "success"
        assert updated["retry_count"] == 0
        assert updated["last_fetched_at"] == later.isoformat()
        assert updated["next_due_at"] == next_due.isoformat()

    @pytest.mark.asyncio
    async def test_mark_url_failed_applies_backoff(self, tmp_path: Path):
        scheduler, metadata_store = self._create_scheduler(tmp_path)
        scheduler._record_progress_failed = AsyncMock()

        await scheduler._mark_url_failed("https://example.com/retry", reason="Timeout")

        saved = metadata_store._data["https://example.com/retry"]
        assert saved["last_status"] == "failed"
        assert saved["retry_count"] == 1

        next_due = datetime.fromisoformat(saved["next_due_at"])
        delta = next_due - datetime.now(timezone.utc)
        assert timedelta(minutes=30) < delta <= timedelta(hours=2)
        scheduler._record_progress_failed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_due_urls_filters_future_entries(self, tmp_path: Path):
        scheduler, metadata_store = self._create_scheduler(tmp_path)
        now = datetime.now(timezone.utc)
        await metadata_store.save_url_metadata(
            {
                "url": "https://example.com/due",
                "discovered_from": None,
                "first_seen_at": now.isoformat(),
                "last_fetched_at": None,
                "next_due_at": now.isoformat(),
                "last_status": "pending",
                "retry_count": 0,
            }
        )
        await metadata_store.save_url_metadata(
            {
                "url": "https://example.com/future",
                "discovered_from": None,
                "first_seen_at": now.isoformat(),
                "last_fetched_at": None,
                "next_due_at": (now + timedelta(days=1)).isoformat(),
                "last_status": "pending",
                "retry_count": 0,
            }
        )

        due = await scheduler._get_due_urls()

        assert due == {"https://example.com/due"}

    @pytest.mark.asyncio
    async def test_get_last_sync_time_handles_errors(self, tmp_path: Path) -> None:
        scheduler, _ = self._create_scheduler(tmp_path)
        scheduler.metadata_store.get_last_sync_time = AsyncMock(side_effect=RuntimeError("boom"))

        result = await scheduler._get_last_sync_time()

        assert result is None

    @pytest.mark.asyncio
    async def test_save_last_sync_time_swallows_exceptions(self, tmp_path: Path) -> None:
        scheduler, _ = self._create_scheduler(tmp_path)
        calls: list[str] = []

        async def _fail(_: datetime):
            calls.append("called")
            raise RuntimeError("boom")

        scheduler.metadata_store.save_last_sync_time = _fail  # type: ignore[assignment]

        await scheduler._save_last_sync_time(datetime.now(timezone.utc))

        assert calls == ["called"]


@pytest.mark.unit
class TestSyncSchedulerUrlProcessing:
    """Covers URL processing paths including skips, success, and failure."""

    def _create_scheduler(self, tmp_path: Path):
        scheduler, metadata_store = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler._record_progress_processed = AsyncMock()
        scheduler._record_progress_skipped = AsyncMock()
        scheduler._record_progress_failed = AsyncMock()
        return scheduler, metadata_store

    @pytest.mark.asyncio
    async def test_process_url_skips_recently_fetched(self, tmp_path: Path):
        scheduler, metadata_store = self._create_scheduler(tmp_path)
        scheduler.cache_service_factory = MagicMock()

        now = datetime.now(timezone.utc)
        metadata_store._data["https://example.com/recent"] = {
            "url": "https://example.com/recent",
            "discovered_from": None,
            "first_seen_at": now.isoformat(),
            "last_fetched_at": (now - timedelta(hours=1)).isoformat(),
            "next_due_at": now.isoformat(),
            "last_status": "success",
            "retry_count": 0,
        }

        await scheduler._process_url("https://example.com/recent")

        scheduler.cache_service_factory.assert_not_called()
        assert scheduler.stats["urls_skipped"] == 1
        scheduler._record_progress_skipped.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_url_updates_metadata_on_success(self, tmp_path: Path):
        scheduler, metadata_store = self._create_scheduler(tmp_path)
        cache_service = _FakeCacheService(({"content": "ok"}, False, None))
        scheduler.cache_service_factory = lambda: cache_service

        await scheduler._process_url("https://example.com/fresh")

        saved = metadata_store._data["https://example.com/fresh"]
        assert saved["last_status"] == "success"
        assert saved["retry_count"] == 0
        assert scheduler.stats["urls_fetched"] == 1
        assert cache_service.calls == ["https://example.com/fresh"]
        scheduler._record_progress_processed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_url_marks_failure_when_fetch_missing(self, tmp_path: Path):
        scheduler, _ = self._create_scheduler(tmp_path)
        cache_service = _FakeCacheService((None, False, "fetch_failed"))
        scheduler.cache_service_factory = lambda: cache_service
        scheduler._mark_url_failed = AsyncMock()

        await scheduler._process_url("https://example.com/missing")

        scheduler._mark_url_failed.assert_awaited_once()
        scheduler._record_progress_failed.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_url_bypass_idempotency_allows_recent_fetch(self, tmp_path: Path):
        scheduler, metadata_store = self._create_scheduler(tmp_path)
        cache_service = _FakeCacheService(({"content": "ok"}, False, None))
        scheduler.cache_service_factory = lambda: cache_service

        now = datetime.now(timezone.utc)
        metadata_store._data["https://example.com/recent"] = {
            "url": "https://example.com/recent",
            "discovered_from": None,
            "first_seen_at": now.isoformat(),
            "last_fetched_at": now.isoformat(),
            "next_due_at": now.isoformat(),
            "last_status": "success",
            "retry_count": 0,
        }

        # First run without bypass should skip due to recency
        await scheduler._process_url("https://example.com/recent")
        assert cache_service.calls == []
        assert scheduler.stats["urls_skipped"] == 1

        # Enable bypass and ensure URL is processed despite recent fetch
        scheduler._bypass_idempotency = True
        scheduler.stats["urls_skipped"] = 0
        scheduler._record_progress_processed.reset_mock()

        await scheduler._process_url("https://example.com/recent")

        assert cache_service.calls == ["https://example.com/recent"]
        assert scheduler.stats["urls_skipped"] == 0
        scheduler._record_progress_processed.assert_awaited_once()


@pytest.mark.unit
class TestSyncSchedulerMetadataInstrumentation:
    """Validates metadata snapshotting and stats aggregation."""

    def _metadata_payload(
        self, *, url: str, first_seen: datetime, last_fetched: datetime | None, next_due: datetime, status: str
    ) -> dict:
        return {
            "url": url,
            "discovered_from": None,
            "first_seen_at": first_seen.isoformat(),
            "last_fetched_at": last_fetched.isoformat() if last_fetched else None,
            "next_due_at": next_due.isoformat(),
            "last_status": status,
            "retry_count": 0,
        }

    def test_update_metadata_stats_populates_fields(self, tmp_path: Path):
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        now = datetime.now(timezone.utc)
        entries = [
            self._metadata_payload(
                url="https://example.com/a",
                first_seen=now - timedelta(days=5),
                last_fetched=now - timedelta(hours=2),
                next_due=now - timedelta(minutes=5),
                status="success",
            ),
            self._metadata_payload(
                url="https://example.com/b",
                first_seen=now - timedelta(days=3),
                last_fetched=None,
                next_due=now + timedelta(days=1),
                status="pending",
            ),
        ]

        scheduler._update_metadata_stats(entries)

        assert scheduler.stats["metadata_total_urls"] == 2
        assert scheduler.stats["metadata_due_urls"] == 1
        assert scheduler.stats["metadata_successful"] == 1
        assert scheduler.stats["metadata_pending"] == 1
        assert scheduler.stats["metadata_first_seen_at"] == (now - timedelta(days=5)).isoformat()
        assert scheduler.stats["metadata_last_success_at"] == (now - timedelta(hours=2)).isoformat()
        assert len(scheduler.stats["metadata_sample"]) == 2

    @pytest.mark.asyncio
    async def test_write_metadata_snapshot_tracks_latest_file(self, tmp_path: Path):
        scheduler, metadata_store = _create_scheduler_with_in_memory_store(tmp_path)
        now = datetime.now(timezone.utc)
        entries = [
            self._metadata_payload(
                url="https://example.com/a",
                first_seen=now,
                last_fetched=now,
                next_due=now,
                status="success",
            )
        ]

        await scheduler._write_metadata_snapshot(entries)

        assert "metadata_snapshot_latest" in metadata_store._debug_snapshots
        snapshot_path = scheduler.stats["metadata_snapshot_path"]
        assert snapshot_path is not None and snapshot_path.endswith("metadata_snapshot_latest.debug.json")


@pytest.mark.unit
class TestSyncSchedulerEntryDiscovery:
    """Ensures entry URL discovery orchestrates crawler and resolution."""

    def _create_scheduler(self, tmp_path: Path):
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler.entry_urls = ["https://example.com/docs/"]
        return scheduler

    @pytest.mark.asyncio
    async def test_discover_urls_from_entry_combines_sources(self, tmp_path: Path):
        scheduler = self._create_scheduler(tmp_path)
        scheduler._resolve_entry_url_redirects = AsyncMock(return_value={"https://example.com/docs/"})
        scheduler._crawl_links_from_roots = AsyncMock(return_value={"https://example.com/api/"})

        result = await scheduler._discover_urls_from_entry(force_crawl=True)

        assert result == {"https://example.com/docs/", "https://example.com/api/"}
        scheduler._crawl_links_from_roots.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_discover_urls_handles_empty_resolution(self, tmp_path: Path):
        scheduler = self._create_scheduler(tmp_path)
        scheduler._resolve_entry_url_redirects = AsyncMock(return_value=set())
        scheduler._crawl_links_from_roots = AsyncMock()

        result = await scheduler._discover_urls_from_entry()

        assert result == set()
        scheduler._crawl_links_from_roots.assert_not_called()


@pytest.mark.unit
class TestSyncSchedulerResolveEntryUrls:
    """Tests redirect resolution logic for entry URLs."""

    def _create_scheduler(self, tmp_path: Path):
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        return scheduler

    @pytest.mark.asyncio
    async def test_resolve_entry_url_redirects_filters_disallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        scheduler = self._create_scheduler(tmp_path)
        responses = {
            "https://example.com/docs/": "https://example.com/docs/",
            "https://example.com/skip": "skip://blocked",
        }

        def _fake_client_factory(*args, **kwargs):
            return _FakeAsyncHTTPClient(responses)

        monkeypatch.setattr("docs_mcp_server.utils.sync_scheduler.httpx.AsyncClient", _fake_client_factory)

        result = await scheduler._resolve_entry_url_redirects(list(responses.keys()))

        assert result == {"https://example.com/docs/"}

    @pytest.mark.asyncio
    async def test_resolve_entry_url_redirects_falls_back_on_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        scheduler = self._create_scheduler(tmp_path)
        responses = {"https://example.com/docs/": "https://example.com/docs/"}

        def _erroring_client_factory(*args, **kwargs):
            return _FakeAsyncHTTPClient(responses, errors={"https://example.com/docs/"})

        monkeypatch.setattr("docs_mcp_server.utils.sync_scheduler.httpx.AsyncClient", _erroring_client_factory)

        result = await scheduler._resolve_entry_url_redirects(["https://example.com/docs/"])

        assert result == {"https://example.com/docs/"}

    @pytest.mark.asyncio
    async def test_resolve_entry_url_redirects_runs_head_calls_in_parallel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        scheduler = self._create_scheduler(tmp_path)
        per_request_delay = 0.3
        responses = {
            "https://example.com/docs/": "https://example.com/docs/",
            "https://example.com/api/": "https://example.com/api/",
        }

        def _delayed_client_factory(*args, **kwargs):
            return _FakeAsyncHTTPClient(responses, delay_seconds=per_request_delay)

        monkeypatch.setattr("docs_mcp_server.utils.sync_scheduler.httpx.AsyncClient", _delayed_client_factory)

        start = time.perf_counter()
        await scheduler._resolve_entry_url_redirects(list(responses.keys()))
        duration = time.perf_counter() - start

        # With sequential HEAD requests the runtime would exceed (delay * 2).
        assert duration < per_request_delay * 1.9


@pytest.mark.unit
class TestSyncSchedulerLinkCrawling:
    """Verify `_crawl_links_from_roots` orchestrates the crawler + processor."""

    @pytest.mark.asyncio
    async def test_crawl_links_skips_recent_metadata_and_processes_new_urls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        scheduler, metadata_store = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler._process_url = AsyncMock()

        recent_url = "https://example.com/recent"
        fresh_url = "https://example.com/fresh"
        metadata_store.metadata_root.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha256(recent_url.encode()).hexdigest()
        meta_path = metadata_store.metadata_root / f"url_{digest}.json"
        meta_path.write_text(
            json.dumps(
                {
                    "url": recent_url,
                    "last_fetched_at": datetime.now(timezone.utc).isoformat(),
                    "next_due_at": datetime.now(timezone.utc).isoformat(),
                    "last_status": "success",
                    "retry_count": 0,
                }
            ),
            encoding="utf-8",
        )

        class _FakeCrawler:
            def __init__(self, root_urls, crawl_config, settings):
                self.root_urls = set(root_urls)
                self.config = crawl_config
                self.settings = settings
                self._crawler_skipped = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def crawl(self):
                for url in {recent_url, fresh_url}:
                    if not self.config.skip_recently_visited(url):
                        self.config.on_url_discovered(url)
                    else:
                        self._crawler_skipped += 1
                await asyncio.sleep(0)
                return self.root_urls.union({recent_url, fresh_url})

        monkeypatch.setattr("docs_mcp_server.utils.sync_scheduler.EfficientCrawler", _FakeCrawler)

        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "call_soon_threadsafe", lambda callback, *args, **kwargs: callback(*args, **kwargs))

        result = await scheduler._crawl_links_from_roots({"https://example.com/"})

        assert result == {recent_url, fresh_url}
        assert scheduler._process_url.await_count == 1
        scheduler._process_url.assert_awaited_once_with(fresh_url, sitemap_lastmod=None)

    @pytest.mark.asyncio
    async def test_crawl_links_returns_empty_on_crawler_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler._process_url = AsyncMock()

        class _ErrorCrawler:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def crawl(self):
                raise RuntimeError("boom")

        monkeypatch.setattr(
            "docs_mcp_server.utils.sync_scheduler.EfficientCrawler", lambda *args, **kwargs: _ErrorCrawler()
        )

        result = await scheduler._crawl_links_from_roots({"https://example.com/"})

        assert result == set()
        scheduler._process_url.assert_not_called()


@pytest.mark.unit
class TestSyncSchedulerFetchSitemaps:
    """Validate `_fetch_and_check_sitemap` handles snapshots and change detection."""

    SITEMAP_URL = "https://example.com/sitemap.xml"
    SITEMAP_CONTENT = b"""<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/page</loc><lastmod>2025-12-01T00:00:00Z</lastmod></url></urlset>"""

    class _FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self):
            return None

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.requests: list[str] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str):
            self.requests.append(url)
            return TestSyncSchedulerFetchSitemaps._FakeResponse(TestSyncSchedulerFetchSitemaps.SITEMAP_CONTENT)

    @pytest.mark.asyncio
    async def test_fetch_and_check_sitemap_detects_changes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        scheduler, metadata_store = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler.sitemap_urls = [self.SITEMAP_URL]

        monkeypatch.setattr(
            "docs_mcp_server.utils.sync_scheduler.httpx.AsyncClient",
            lambda *args, **kwargs: self._FakeAsyncClient(),
        )

        changed, entries = await scheduler._fetch_and_check_sitemap()

        assert changed is True
        assert len(entries) == 1
        assert str(entries[0].url) == "https://example.com/page"

        snapshot_key = f"sitemap_{hashlib.sha256(self.SITEMAP_URL.encode()).hexdigest()[:8]}"
        assert snapshot_key in metadata_store._snapshots
        assert (
            metadata_store._snapshots[snapshot_key]["content_hash"] == hashlib.sha256(self.SITEMAP_CONTENT).hexdigest()
        )

    @pytest.mark.asyncio
    async def test_fetch_and_check_sitemap_reports_no_change_when_hash_matches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        scheduler, metadata_store = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler.sitemap_urls = [self.SITEMAP_URL]

        snapshot_key = f"sitemap_{hashlib.sha256(self.SITEMAP_URL.encode()).hexdigest()[:8]}"
        metadata_store._snapshots[snapshot_key] = {"content_hash": hashlib.sha256(self.SITEMAP_CONTENT).hexdigest()}

        monkeypatch.setattr(
            "docs_mcp_server.utils.sync_scheduler.httpx.AsyncClient",
            lambda *args, **kwargs: self._FakeAsyncClient(),
        )

        changed, entries = await scheduler._fetch_and_check_sitemap()

        assert changed is False
        assert entries and len(entries) == 1

        # Snapshot should be refreshed even when unchanged
        assert (
            metadata_store._snapshots[snapshot_key]["content_hash"] == hashlib.sha256(self.SITEMAP_CONTENT).hexdigest()
        )


@pytest.mark.unit
class TestSyncSchedulerDeleteBlacklistedCaches:
    """Validates blacklist-based cache deletion logic."""

    @pytest.mark.asyncio
    async def test_delete_blacklisted_caches_removes_matches(self, tmp_path: Path):
        settings = _DummySettings(blacklist_prefixes=["https://blocked.com/"])
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path, settings=settings)
        repo = _FakeDocumentRepository(
            [
                "https://blocked.com/page",
                "https://allowed.com/doc",
            ]
        )
        scheduler.uow_factory = lambda: _FakeUnitOfWork(repo)

        stats = await scheduler.delete_blacklisted_caches()

        assert stats["checked"] == 2
        assert stats["deleted"] == 1
        assert stats["errors"] == 0
        assert repo.deleted == ["https://blocked.com/page"]

    @pytest.mark.asyncio
    async def test_delete_blacklisted_caches_skips_without_rules(self, tmp_path: Path):
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)

        stats = await scheduler.delete_blacklisted_caches()

        assert stats == {"checked": 0, "deleted": 0, "errors": 0}


@pytest.mark.unit
class TestSyncSchedulerCronLoop:
    """Validates cron-based run loop timing and error backoff behavior."""

    @pytest.mark.asyncio
    async def test_run_loop_respects_sleep_bounds_and_backoff(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler.refresh_schedule = "* * * * *"

        class _DeterministicCron:
            def __init__(self):
                self.call_count = 0

            def schedule(self, start_date):
                return self

            def next(self):
                self.call_count += 1
                now = datetime.now(timezone.utc)
                if self.call_count == 1:
                    return now - timedelta(seconds=1)  # due immediately
                if self.call_count == 2:
                    return now + timedelta(minutes=5)  # future -> sleep capped at 60s
                return now - timedelta(seconds=1)  # trigger error path

        scheduler.cron_instance = _DeterministicCron()
        scheduler._get_last_sync_time = AsyncMock(return_value=None)
        scheduler._save_last_sync_time = AsyncMock()
        scheduler._sync_cycle = AsyncMock(side_effect=[None, RuntimeError("boom")])
        scheduler.running = True

        sleep_calls: list[float] = []
        real_sleep = asyncio.sleep

        async def fake_sleep(delay: float):
            sleep_calls.append(delay)
            if len(sleep_calls) >= 2:
                scheduler.running = False
            await real_sleep(0)

        monkeypatch.setattr("docs_mcp_server.utils.sync_scheduler.asyncio.sleep", fake_sleep)

        loop_task = asyncio.create_task(scheduler._run_loop())
        await asyncio.wait_for(loop_task, timeout=1)

        assert scheduler._sync_cycle.await_count == 2
        assert scheduler._save_last_sync_time.await_count == 1
        assert sleep_calls == [60, 60]
        assert scheduler.stats["total_syncs"] == 1
        assert scheduler.stats["errors"] == 1
        assert scheduler.stats["next_sync_at"] is not None

    @pytest.mark.asyncio
    async def test_run_loop_idles_without_schedule(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler.cron_instance = None
        scheduler.running = True

        wait_calls: list[float] = []

        real_wait_for = asyncio.wait_for

        async def fake_wait_for(_awaitable, timeout):
            wait_calls.append(timeout)
            scheduler.running = False
            raise asyncio.TimeoutError

        monkeypatch.setattr("docs_mcp_server.utils.sync_scheduler.asyncio.wait_for", fake_wait_for)

        loop_task = asyncio.create_task(scheduler._run_loop())
        await real_wait_for(loop_task, timeout=1)

        assert wait_calls == [60.0]

    @pytest.mark.asyncio
    async def test_run_loop_sleeps_for_short_intervals_before_shutting_down(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler.refresh_schedule = "* * * * *"

        class _ShortIntervalCron:
            def __init__(self):
                self.calls = 0

            def schedule(self, *_args, **_kwargs):
                return self

            def next(self):
                self.calls += 1
                now = datetime.now(timezone.utc)
                if self.calls == 1:
                    return now + timedelta(seconds=30)
                return now - timedelta(seconds=1)

        scheduler.cron_instance = _ShortIntervalCron()
        scheduler._get_last_sync_time = AsyncMock(return_value=None)
        scheduler._sync_cycle = AsyncMock()
        scheduler._save_last_sync_time = AsyncMock()
        scheduler.running = True

        sleep_calls: list[float] = []

        async def fake_sleep(delay: float):
            sleep_calls.append(delay)
            scheduler.running = False

        monkeypatch.setattr("docs_mcp_server.utils.sync_scheduler.asyncio.sleep", fake_sleep)

        loop_task = asyncio.create_task(scheduler._run_loop())
        await asyncio.wait_for(loop_task, timeout=1)

        assert sleep_calls == pytest.approx([30.0], rel=1e-3)

    @pytest.mark.asyncio
    async def test_run_loop_handles_cron_schedule_errors(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler.refresh_schedule = "* * * * *"

        class _ErrorCron:
            def schedule(self, *_args, **_kwargs):
                return self

            def next(self):
                raise RuntimeError("boom")

        scheduler.cron_instance = _ErrorCron()
        scheduler.running = True
        scheduler._get_last_sync_time = AsyncMock(return_value=None)
        scheduler._sync_cycle = AsyncMock()

        sleep_calls: list[float] = []

        async def fake_sleep(delay: float):
            sleep_calls.append(delay)
            scheduler.running = False

        monkeypatch.setattr("docs_mcp_server.utils.sync_scheduler.asyncio.sleep", fake_sleep)

        loop_task = asyncio.create_task(scheduler._run_loop())
        await asyncio.wait_for(loop_task, timeout=1)

        assert sleep_calls == [60]
        assert scheduler.stats["errors"] == 1
        assert scheduler._sync_cycle.await_count == 0


@pytest.mark.unit
class TestSyncSchedulerMetadataAccess:
    """Cover metadata helpers that handle persistence failures."""

    @pytest.mark.asyncio
    async def test_get_last_sync_time_handles_errors(self, tmp_path: Path):
        scheduler, metadata_store = _create_scheduler_with_in_memory_store(tmp_path)
        metadata_store.get_last_sync_time = AsyncMock(side_effect=RuntimeError("boom"))

        assert await scheduler._get_last_sync_time() is None

    @pytest.mark.asyncio
    async def test_save_last_sync_time_does_not_raise(self, tmp_path: Path):
        scheduler, metadata_store = _create_scheduler_with_in_memory_store(tmp_path)
        metadata_store.save_last_sync_time = AsyncMock(side_effect=RuntimeError("boom"))

        await scheduler._save_last_sync_time(datetime.now(timezone.utc))
        metadata_store.save_last_sync_time.assert_awaited_once()


@pytest.mark.unit
class TestSyncSchedulerNextDue:
    """Validate next-due computation across freshness windows."""

    def _create_scheduler(self, **kwargs):
        module = _import_sync_scheduler()
        sync_scheduler_cls = module.SyncScheduler

        mock_settings = MagicMock()
        mock_settings.default_sync_interval_days = 7
        mock_settings.max_sync_interval_days = 30
        mock_settings.enable_crawler = True
        mock_settings.max_crawl_pages = 10
        mock_settings.max_concurrent_requests = 2
        mock_settings.get_url_blacklist_prefixes = MagicMock(return_value=[])
        mock_settings.should_process_url = MagicMock(return_value=True)
        mock_settings.get_random_user_agent = MagicMock(return_value="unit-agent")

        if "sitemap_urls" not in kwargs and "entry_urls" not in kwargs:
            kwargs["sitemap_urls"] = ["https://example.com/sitemap.xml"]
        config = _build_scheduler_config(kwargs, module)

        defaults = {
            "settings": mock_settings,
            "uow_factory": MagicMock(),
            "cache_service_factory": MagicMock(),
            "metadata_store": MagicMock(),
            "progress_store": _progress_store_stub(),
            "tenant_codename": "test-tenant",
            "config": config,
        }
        defaults.update(kwargs)
        return sync_scheduler_cls(**defaults)

    def test_next_due_defaults_to_configured_interval(self):
        scheduler = self._create_scheduler()
        start = datetime.now(timezone.utc)

        due = scheduler._calculate_next_due()
        delta_seconds = (due - start).total_seconds()
        expected = scheduler.settings.default_sync_interval_days * 86400

        assert delta_seconds == pytest.approx(expected, rel=1e-2)

    def test_next_due_recent_lastmod_returns_one_day(self):
        scheduler = self._create_scheduler()
        lastmod = datetime.now(timezone.utc) - timedelta(days=1)
        start = datetime.now(timezone.utc)

        due = scheduler._calculate_next_due(lastmod)
        delta_seconds = (due - start).total_seconds()

        assert delta_seconds == pytest.approx(86400, rel=1e-2)

    def test_next_due_moderate_lastmod_uses_default_interval(self):
        scheduler = self._create_scheduler()
        lastmod = datetime.now() - timedelta(days=10)  # naive timestamp
        start = datetime.now(timezone.utc)

        due = scheduler._calculate_next_due(lastmod)
        delta_seconds = (due - start).total_seconds()
        expected = scheduler.settings.default_sync_interval_days * 86400

        assert delta_seconds == pytest.approx(expected, rel=1e-2)

    def test_next_due_old_lastmod_uses_max_interval(self):
        scheduler = self._create_scheduler()
        lastmod = datetime.now(timezone.utc) - timedelta(days=40)
        start = datetime.now(timezone.utc)

        due = scheduler._calculate_next_due(lastmod)
        delta_seconds = (due - start).total_seconds()
        expected = scheduler.settings.max_sync_interval_days * 86400

        assert delta_seconds == pytest.approx(expected, rel=1e-2)


@pytest.mark.unit
class TestSyncSchedulerRecentSkip:
    """Cover the idempotent skip path for recently fetched URLs."""

    @pytest.mark.asyncio
    async def test_process_url_skips_recent_successful_fetch(self, tmp_path: Path):
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        sync_scheduler = _import_sync_scheduler()
        SyncMetadata = sync_scheduler.SyncMetadata

        url = "https://example.com/recent"
        metadata = SyncMetadata(
            url=url,
            last_fetched_at=datetime.now(timezone.utc) - timedelta(hours=1),
            last_status="success",
        )
        scheduler.metadata_store.load_url_metadata = AsyncMock(return_value=metadata.to_dict())
        scheduler.cache_service_factory = MagicMock()

        await scheduler._process_url(url)

        scheduler.cache_service_factory.assert_not_called()
        assert scheduler.stats["urls_skipped"] == 1


@pytest.mark.unit
class TestSyncSchedulerBatchProcessing:
    """Covers batch chunking logic during sync cycles."""

    @pytest.mark.asyncio
    async def test_sync_cycle_processes_urls_in_configured_chunks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler.settings.max_concurrent_requests = 2
        scheduler._load_sitemap_metadata = AsyncMock()
        scheduler._update_cache_stats = AsyncMock()
        scheduler.delete_blacklisted_caches = AsyncMock(return_value={"checked": 0, "deleted": 0, "errors": 0})
        scheduler._fetch_and_check_sitemap = AsyncMock(return_value=(True, ["entry"]))
        scheduler._extract_urls_from_sitemap = MagicMock(
            return_value=(
                {"https://example.com/a", "https://example.com/b", "https://example.com/c"},
                {},
            )
        )

        async def passthrough(urls: set[str], *_args, **_kwargs):
            return urls

        scheduler._apply_crawler_if_needed = AsyncMock(side_effect=passthrough)
        scheduler._get_due_urls = AsyncMock(return_value={"https://example.com/d", "https://example.com/e"})
        scheduler._has_previous_metadata = AsyncMock(return_value=False)
        scheduler._process_url = AsyncMock(side_effect=[None, None, RuntimeError("boom"), None, None])
        scheduler._mark_url_failed = AsyncMock()

        batch_sizes: list[int] = []

        async def fake_gather(*coroutines, return_exceptions=False):
            batch_sizes.append(len(coroutines))
            results = []
            for coro in coroutines:
                try:
                    results.append(await coro)
                except Exception as exc:  # pragma: no cover - routed via return_exceptions
                    if return_exceptions:
                        results.append(exc)
                    else:
                        raise
            return results

        sleep_intervals: list[float] = []

        async def fake_sleep(delay: float):
            sleep_intervals.append(delay)

        monkeypatch.setattr("docs_mcp_server.utils.sync_scheduler.asyncio.gather", fake_gather)
        monkeypatch.setattr("docs_mcp_server.utils.sync_scheduler.asyncio.sleep", fake_sleep)

        await scheduler._sync_cycle()

        assert scheduler._process_url.await_count == 5
        assert scheduler._mark_url_failed.await_count == 1
        assert scheduler.stats["urls_processed"] == 4
        assert scheduler.stats["errors"] == 1
        assert batch_sizes == [2, 2, 1]
        assert sleep_intervals == [0.5, 0.5, 0.5]
        assert scheduler.stats["queue_depth"] == 0


@pytest.mark.unit
class TestSyncSchedulerEntryModeSyncCycle:
    """Entry-mode schedulers should queue crawler fallbacks correctly."""

    @pytest.mark.asyncio
    async def test_entry_mode_discovers_urls_when_metadata_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        scheduler, _ = _create_scheduler_with_in_memory_store(
            tmp_path, config_kwargs={"entry_urls": ["https://example.com/docs/"]}
        )
        scheduler.mode = "entry"
        scheduler.sitemap_urls = []
        scheduler._load_sitemap_metadata = AsyncMock()
        scheduler._update_cache_stats = AsyncMock()
        scheduler.delete_blacklisted_caches = AsyncMock(return_value={"checked": 0, "deleted": 0, "errors": 0})
        scheduler._get_due_urls = AsyncMock(return_value={"https://example.com/due"})
        scheduler._has_previous_metadata = AsyncMock(return_value=False)
        scheduler._process_url = AsyncMock()

        async def fake_discovery(force_crawl: bool = False):
            raw_urls = {"https://example.com/docs/page1", "skip://blocked"}
            return {u for u in raw_urls if scheduler.settings.should_process_url(u)}

        scheduler._discover_urls_from_entry = AsyncMock(wraps=fake_discovery)

        async def fake_sleep(_delay: float):
            return None

        monkeypatch.setattr("docs_mcp_server.utils.sync_scheduler.asyncio.sleep", fake_sleep)

        await scheduler._sync_cycle()

        scheduler._discover_urls_from_entry.assert_awaited_once()
        scheduled_urls = {call.args[0] for call in scheduler._process_url.await_args_list}
        assert "skip://blocked" not in scheduled_urls
        assert {"https://example.com/docs/page1", "https://example.com/due"}.issubset(scheduled_urls)
        assert scheduler.stats["urls_processed"] == len(scheduled_urls)


@pytest.mark.unit
class TestSyncSchedulerCrawlerDecision:
    """Verify `_apply_crawler_if_needed` honors flags and stats."""

    @pytest.mark.asyncio
    async def test_apply_crawler_runs_when_forced(self, tmp_path: Path):
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler.stats["filtered_urls"] = 5
        scheduler.stats["es_cached_count"] = 0
        scheduler._has_previous_metadata = AsyncMock(return_value=False)
        discovered = {"https://example.com/new"}
        scheduler._crawl_links_from_roots = AsyncMock(return_value=discovered)

        roots = {"https://example.com/root"}
        result = await scheduler._apply_crawler_if_needed(roots, sitemap_changed=False, force_crawler=True)

        scheduler._crawl_links_from_roots.assert_awaited_once_with(roots, force_crawl=True)
        assert result == roots.union(discovered)
        assert scheduler.stats["urls_discovered"] == len(discovered)
        assert scheduler.stats["crawler_total_runs"] == 1
        assert scheduler.stats["last_crawler_run"] is not None

    @pytest.mark.asyncio
    async def test_apply_crawler_skips_when_disabled(self, tmp_path: Path):
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler.settings.enable_crawler = False
        scheduler._crawl_links_from_roots = AsyncMock()

        roots = {"https://example.com/root"}
        result = await scheduler._apply_crawler_if_needed(roots, sitemap_changed=True, force_crawler=True)

        assert result == roots
        scheduler._crawl_links_from_roots.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_apply_crawler_suppressed_when_cache_sufficient(self, tmp_path: Path):
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler.stats["filtered_urls"] = 1
        scheduler.stats["es_cached_count"] = 10
        scheduler._has_previous_metadata = AsyncMock(return_value=True)
        scheduler._crawl_links_from_roots = AsyncMock()

        roots = {"https://example.com/root"}
        result = await scheduler._apply_crawler_if_needed(roots, sitemap_changed=False, force_crawler=False)

        assert result == roots
        scheduler._crawl_links_from_roots.assert_not_awaited()


@pytest.mark.unit
class TestSyncSchedulerProgressCheckpoints:
    """Exercises checkpoint throttling and queue tracking."""

    @pytest.mark.asyncio
    async def test_checkpoint_progress_honors_force_and_history(self, tmp_path: Path):
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        progress = await scheduler._load_or_create_progress()
        scheduler._active_progress = progress

        await scheduler._checkpoint_progress(force=True, keep_history=True)

        save_checkpoint = scheduler.progress_store.save_checkpoint
        assert save_checkpoint.await_count == 1
        call = save_checkpoint.await_args_list[0]
        assert call.args[0] == "test-tenant"
        assert call.kwargs["keep_history"] is True
        assert call.args[1]["tenant_codename"] == "test-tenant"

        save_checkpoint.reset_mock()
        scheduler._last_progress_checkpoint = datetime.now(timezone.utc)
        await scheduler._checkpoint_progress(force=False)
        assert save_checkpoint.await_count == 0

        await scheduler._checkpoint_progress(force=True)
        assert save_checkpoint.await_count == 1

    @pytest.mark.asyncio
    async def test_record_progress_processed_updates_queue_depth(self, tmp_path: Path):
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        progress = await scheduler._load_or_create_progress()
        progress.start_discovery()
        progress.add_discovered_urls({"https://example.com/a", "https://example.com/b"})
        scheduler._active_progress = progress
        scheduler._checkpoint_interval = timedelta(seconds=0)
        scheduler.progress_store.save_checkpoint.reset_mock()

        await scheduler._record_progress_processed("https://example.com/a")

        assert scheduler.stats["queue_depth"] == 1
        assert scheduler.progress_store.save_checkpoint.await_count == 1


@pytest.mark.unit
class TestSyncSchedulerLoopBehavior:
    """Exercised cron loop, stop semantics, and status snapshots."""

    @pytest.mark.asyncio
    async def test_run_loop_triggers_sync_and_records_stats(self, tmp_path: Path):
        scheduler, _ = _create_scheduler_with_in_memory_store(
            tmp_path,
            config_kwargs={"refresh_schedule": "0 * * * *"},
        )
        cron = MagicMock()
        schedule = MagicMock()
        now = datetime.now(timezone.utc)
        schedule.next.return_value = now
        cron.schedule.return_value = schedule
        scheduler.cron_instance = cron
        scheduler._get_last_sync_time = AsyncMock(return_value=None)
        scheduler._save_last_sync_time = AsyncMock()

        async def stop_loop():
            scheduler.running = False

        scheduler._sync_cycle = AsyncMock(side_effect=stop_loop)
        scheduler.running = True

        await scheduler._run_loop()

        assert scheduler._sync_cycle.await_count == 1
        assert scheduler.stats["total_syncs"] == 1
        assert scheduler.stats["next_sync_at"] == now.isoformat()

    @pytest.mark.asyncio
    async def test_run_loop_sleeps_when_schedule_in_future(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        scheduler, _ = _create_scheduler_with_in_memory_store(
            tmp_path,
            config_kwargs={"refresh_schedule": "0 * * * *"},
        )
        cron = MagicMock()
        schedule = MagicMock()
        future = datetime.now(timezone.utc) + timedelta(minutes=5)
        schedule.next.return_value = future
        cron.schedule.return_value = schedule
        scheduler.cron_instance = cron
        scheduler._get_last_sync_time = AsyncMock(return_value=None)
        scheduler._sync_cycle = AsyncMock()

        sleep_calls: list[float] = []

        async def fake_sleep(delay: float):
            sleep_calls.append(delay)
            scheduler.running = False

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        scheduler.running = True

        await scheduler._run_loop()

        assert sleep_calls and sleep_calls[-1] <= 60.0
        assert scheduler.stats["total_syncs"] == 0

    @pytest.mark.asyncio
    async def test_run_loop_backoffs_on_errors(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        scheduler, _ = _create_scheduler_with_in_memory_store(
            tmp_path,
            config_kwargs={"refresh_schedule": "0 * * * *"},
        )
        cron = MagicMock()
        schedule = MagicMock()
        schedule.next.return_value = datetime.now(timezone.utc)
        cron.schedule.return_value = schedule
        scheduler.cron_instance = cron
        scheduler._get_last_sync_time = AsyncMock(side_effect=RuntimeError("boom"))
        scheduler._sync_cycle = AsyncMock()

        sleep_calls: list[float] = []

        async def fake_sleep(delay: float):
            sleep_calls.append(delay)
            scheduler.running = False

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        scheduler.running = True

        await scheduler._run_loop()

        assert scheduler.stats["errors"] == 1
        assert sleep_calls and sleep_calls[-1] == pytest.approx(60.0)

    def test_get_stats_returns_snapshot(self, tmp_path: Path):
        scheduler, _ = _create_scheduler_with_in_memory_store(tmp_path)
        scheduler.stats.update(
            {
                "total_syncs": 3,
                "errors": 1,
                "last_sync_at": "ready",
                "next_sync_at": "soon",
            }
        )

        snapshot = scheduler.get_stats()

        assert snapshot["total_syncs"] == 3
        assert snapshot["errors"] == 1
        assert snapshot["last_sync_at"] == "ready"
        assert snapshot["next_sync_at"] == "soon"

        snapshot["total_syncs"] = 0
        assert scheduler.stats["total_syncs"] == 3
