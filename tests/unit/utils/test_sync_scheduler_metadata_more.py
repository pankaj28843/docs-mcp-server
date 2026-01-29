"""Additional unit tests for SyncSchedulerMetadataMixin helpers."""

from datetime import timezone
from types import SimpleNamespace
from typing import ClassVar

import pytest

from docs_mcp_server.utils.sync_scheduler_metadata import SyncSchedulerMetadataMixin


class _Stats:
    metadata_total_urls = 0
    metadata_due_urls = 0
    metadata_successful = 0
    metadata_pending = 0
    metadata_first_seen_at = None
    metadata_last_success_at = None
    metadata_sample: ClassVar[list[dict]] = []
    failed_url_count = 0
    failure_sample: ClassVar[list[dict]] = []
    storage_doc_count = 0
    fallback_attempts = 0
    fallback_successes = 0
    fallback_failures = 0


class _MetaStore:
    def __init__(self):
        self.ready_called = False
        self.cleanup_called = False

    async def save_summary(self, _payload):
        return None

    async def save_debug_snapshot(self, _name, _payload):
        return None

    async def get_sitemap_snapshot(self, _snapshot_id):
        raise RuntimeError("boom")

    def ensure_ready(self):
        self.ready_called = True

    async def cleanup_legacy_artifacts(self):
        self.cleanup_called = True


class _Uow:
    class Documents:
        @staticmethod
        async def count():
            return 1

    documents = Documents

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


class _Runner(SyncSchedulerMetadataMixin):
    def __init__(self):
        self.stats = _Stats()
        self.settings = SimpleNamespace(default_sync_interval_days=7, max_sync_interval_days=30)
        self.metadata_store = _MetaStore()
        self.schedule_interval_hours = 24
        self.cache_service_factory = lambda: None
        self.uow_factory = lambda: _Uow()
        self.sitemap_metadata = SimpleNamespace(total_urls=0)


@pytest.mark.unit
def test_parse_iso_timestamp_handles_missing_and_naive_values():
    runner = _Runner()
    assert runner._parse_iso_timestamp(None) is None
    assert runner._parse_iso_timestamp("invalid") is None

    parsed = runner._parse_iso_timestamp("2025-01-01T10:00:00")
    assert parsed.tzinfo == timezone.utc


@pytest.mark.unit
def test_select_metadata_sample_handles_empty_and_limit():
    runner = _Runner()
    assert runner._select_metadata_sample([], limit=5) == []
    assert runner._select_metadata_sample([{"url": "x"}], limit=0) == []


@pytest.mark.unit
def test_update_metadata_stats_skips_invalid_payload():
    runner = _Runner()
    runner._update_metadata_stats([{"bad": "payload"}])

    assert runner.stats.metadata_total_urls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_sitemap_metadata_handles_failure():
    runner = _Runner()

    await runner._load_sitemap_metadata()

    assert runner.sitemap_metadata is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_sitemap_metadata_handles_exception(monkeypatch):
    runner = _Runner()

    async def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "_get_sitemap_snapshot", _raise)

    await runner._load_sitemap_metadata()

    assert runner.sitemap_metadata is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_cache_stats_handles_errors():
    runner = _Runner()

    await runner._update_cache_stats()

    assert runner.stats.storage_doc_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_cache_stats_logs_percentage():
    runner = _Runner()
    runner.sitemap_metadata = SimpleNamespace(total_urls=2)

    await runner._update_cache_stats()

    assert runner.stats.storage_doc_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_cache_stats_survives_count_failure():
    runner = _Runner()

    class _FailingUow:
        class Documents:
            @staticmethod
            async def count():
                raise RuntimeError("boom")

        documents = Documents

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

    runner.uow_factory = lambda: _FailingUow()

    await runner._update_cache_stats()

    assert runner.stats.storage_doc_count == 0


@pytest.mark.unit
def test_refresh_fetcher_metrics_handles_missing_cache():
    runner = _Runner()

    runner._refresh_fetcher_metrics(cache_service=None)

    assert runner.stats.fallback_attempts == 0


@pytest.mark.unit
def test_refresh_fetcher_metrics_handles_invalid_values():
    runner = _Runner()

    class BadMetrics:
        def __int__(self):
            raise ValueError("bad")

    service = SimpleNamespace(get_fetcher_stats=lambda: {"fallback_attempts": BadMetrics()})
    runner._refresh_fetcher_metrics(cache_service=service)

    assert runner.stats.fallback_attempts == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_metadata_can_be_accessed_calls_store():
    runner = _Runner()

    await runner._ensure_metadata_can_be_accessed()

    assert runner.metadata_store.ready_called is True
    assert runner.metadata_store.cleanup_called is True
