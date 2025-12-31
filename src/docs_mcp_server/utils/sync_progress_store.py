"""Filesystem-backed store for SyncProgress aggregates."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

import anyio
from anyio import to_thread

from docs_mcp_server.domain.sync_progress import SyncProgress


logger = logging.getLogger(__name__)


class SyncProgressStore:
    """Persist SyncProgress using atomic filesystem writes."""

    def __init__(self, base_path: Path, *, dir_name: str = "__sync_progress"):
        self.base_path = base_path
        self.store_dir = base_path / dir_name
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir = self.store_dir / "history"
        self.history_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, progress: SyncProgress) -> None:
        """Persist SyncProgress aggregate."""
        path = self._progress_path(progress.tenant_codename)
        await self._write_json_atomic(path, progress.to_dict())

    async def load(self, tenant_codename: str) -> SyncProgress | None:
        """Load SyncProgress for tenant, returns None if missing."""
        path = self._progress_path(tenant_codename)
        data = await self._read_json(path)
        if not data:
            return None
        try:
            return SyncProgress.from_dict(data)
        except Exception as err:  # pragma: no cover - log + skip corrupt entries
            logger.warning("Failed to deserialize progress for %s: %s", tenant_codename, err)
            return None

    async def delete(self, tenant_codename: str) -> None:
        """Delete progress and checkpoints for tenant."""
        for path in [self._progress_path(tenant_codename), self._checkpoint_path(tenant_codename)]:
            try:
                await to_thread.run_sync(path.unlink)
            except FileNotFoundError:
                continue
            except OSError as err:  # pragma: no cover - best effort cleanup
                logger.debug("Failed to delete %s: %s", path, err)
        # Remove history directory
        history_dir = self._history_dir(tenant_codename)
        if history_dir.exists():
            await to_thread.run_sync(shutil.rmtree, history_dir, True)

    async def save_checkpoint(
        self, tenant_codename: str, checkpoint: dict[str, Any], *, keep_history: bool = False
    ) -> None:
        """Persist latest checkpoint and optionally history entry."""
        checkpoint_path = self._checkpoint_path(tenant_codename)
        await self._write_json_atomic(checkpoint_path, checkpoint)

        if keep_history:
            history_dir = self._history_dir(tenant_codename)
            history_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            history_file = history_dir / f"{timestamp}_{checkpoint['sync_id']}.json"
            await self._write_json_atomic(history_file, checkpoint)

    async def get_latest_for_tenant(self, tenant_codename: str) -> SyncProgress | None:
        """Return latest sync progress for tenant (alias for load)."""
        return await self.load(tenant_codename)

    def _progress_path(self, tenant_codename: str) -> Path:
        return self.store_dir / f"{self._sanitize_tenant(tenant_codename)}.json"

    def _checkpoint_path(self, tenant_codename: str) -> Path:
        return self.store_dir / f"{self._sanitize_tenant(tenant_codename)}.checkpoint.json"

    def _history_dir(self, tenant_codename: str) -> Path:
        return self.history_dir / self._sanitize_tenant(tenant_codename)

    def _sanitize_tenant(self, tenant_codename: str) -> str:
        return tenant_codename.replace("/", "_")

    async def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_suffix = f".{uuid4().hex}.tmp"
        tmp_path = path.with_name(f"{path.name}{tmp_suffix}")
        async with await anyio.open_file(tmp_path, "w", encoding="utf-8") as fp:
            await fp.write(json.dumps(payload, indent=2, sort_keys=True))
        await to_thread.run_sync(_safe_move, tmp_path, path)

    async def _read_json(self, path: Path) -> dict[str, Any] | None:
        try:
            async with await anyio.open_file(path, "r", encoding="utf-8") as fp:
                content = await fp.read()
            return json.loads(content)
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as err:  # pragma: no cover - log + skip corrupt entries
            logger.debug("Failed to read %s: %s", path, err)
            return None


def _safe_move(src: Path, dest: Path) -> None:
    src.replace(dest)
