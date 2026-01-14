"""Additional unit tests for sync models batch runner."""

from __future__ import annotations

import pytest

from docs_mcp_server.domain.sync_progress import SyncProgress
from docs_mcp_server.utils.sync_models import SyncBatchRunner, SyncCyclePlan


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sync_batch_runner_handles_empty_queue():
    progress = SyncProgress.create_new("tenant")
    plan = SyncCyclePlan(
        sitemap_urls=set(),
        sitemap_lastmod_map={},
        sitemap_changed=False,
        due_urls=set(),
        has_previous_metadata=False,
        has_documents=False,
    )

    async def _noop(*_args, **_kwargs):
        return None

    runner = SyncBatchRunner(
        plan=plan,
        queue=[],
        batch_size=1,
        process_url=_noop,
        checkpoint=_noop,
        on_failure=_noop,
        sleep=_noop,
        progress=progress,
    )

    result = await runner.run()

    assert result.total_urls == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sync_batch_runner_handles_on_error_and_on_failure_exceptions():
    progress = SyncProgress.create_new("tenant")
    progress.pending_urls = {"https://example.com/doc"}
    plan = SyncCyclePlan(
        sitemap_urls=set(),
        sitemap_lastmod_map={},
        sitemap_changed=False,
        due_urls=set(),
        has_previous_metadata=True,
        has_documents=True,
    )

    async def _process_url(_url, _lastmod):
        raise RuntimeError("boom")

    async def _noop(*_args, **_kwargs):
        return None

    def _on_error():
        raise RuntimeError("callback boom")

    async def _on_failure(_url, _exc):
        raise RuntimeError("fail boom")

    runner = SyncBatchRunner(
        plan=plan,
        queue=list(progress.pending_urls),
        batch_size=1,
        process_url=_process_url,
        checkpoint=_noop,
        on_failure=_on_failure,
        sleep=_noop,
        progress=progress,
        on_error=_on_error,
    )

    result = await runner.run()

    assert result.failed == 1
