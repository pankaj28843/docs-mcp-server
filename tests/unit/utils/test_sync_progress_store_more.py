"""Additional unit tests for SyncProgressStore delete behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from docs_mcp_server.utils.sync_progress_store import SyncProgressStore


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_removes_history_directory(tmp_path: Path):
    store = SyncProgressStore(tmp_path)
    history_dir = store._history_dir("tenant")
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / "checkpoint.json").write_text("{}", encoding="utf-8")

    await store.delete("tenant")

    assert not history_dir.exists()
