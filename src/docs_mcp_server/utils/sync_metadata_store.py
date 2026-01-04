# """Filesystem-backed store for scheduler metadata and distributed locks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
from typing import Any

import anyio

from .path_builder import PathBuilder


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LockLease:
    """Represents a filesystem-backed lock lease."""

    name: str
    owner: str
    acquired_at: datetime
    expires_at: datetime
    path: Path

    def is_expired(self, *, now: datetime | None = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        return moment >= self.expires_at

    def remaining_seconds(self, *, now: datetime | None = None) -> float:
        moment = now or datetime.now(timezone.utc)
        return max(0.0, (self.expires_at - moment).total_seconds())


class SyncMetadataStore:
    """Persist scheduler bookkeeping separate from document corpus."""

    def __init__(self, tenant_root: Path, *, metadata_dir: str = "__scheduler_meta"):
        self.tenant_root = tenant_root
        self.metadata_root = tenant_root / metadata_dir
        self.metadata_root.mkdir(parents=True, exist_ok=True)
        self._locks_root = self.metadata_root / "locks"
        self._locks_root.mkdir(parents=True, exist_ok=True)

    def ensure_ready(self) -> None:
        """Ensure metadata directory exists."""

        self.metadata_root.mkdir(parents=True, exist_ok=True)

    async def cleanup_legacy_artifacts(self) -> None:
        """Remove legacy sync-meta directories left by older deployments."""

        await anyio.to_thread.run_sync(self._cleanup_legacy_sync)

    async def save_last_sync_time(self, sync_time: datetime) -> None:
        payload = {"last_sync_at": sync_time.isoformat()}
        await self._write_json(self._key_path("meta_last_sync"), payload)

    async def get_last_sync_time(self) -> datetime | None:
        data = await self._read_json(self._key_path("meta_last_sync"))
        if not data:
            return None
        try:
            return datetime.fromisoformat(data["last_sync_at"])
        except (KeyError, ValueError):
            return None

    async def save_sitemap_snapshot(self, snapshot: dict, snapshot_id: str) -> None:
        await self._write_json(self._key_path(f"meta_snapshot_{snapshot_id}"), snapshot)

    async def get_sitemap_snapshot(self, snapshot_id: str) -> dict | None:
        return await self._read_json(self._key_path(f"meta_snapshot_{snapshot_id}"))

    async def save_url_metadata(self, metadata: dict[str, Any]) -> None:
        url = metadata.get("url", "")
        if not url:
            logger.debug("Skipping metadata save with missing URL: %s", metadata)
            return
        await self._write_json(self._url_path(url), metadata)

    async def load_url_metadata(self, url: str) -> dict | None:
        return await self._read_json(self._url_path(url))

    async def list_all_metadata(self) -> list[dict]:
        return await anyio.to_thread.run_sync(self._list_all_metadata_sync)

    def _list_all_metadata_sync(self) -> list[dict]:
        entries: list[dict] = []
        for path in self.metadata_root.glob("url_*.json"):
            try:
                entries.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return entries

    async def save_debug_snapshot(self, name: str, payload: dict[str, Any]) -> None:
        """Persist a debug snapshot payload for instrumentation runs."""

        debug_path = self.metadata_root / f"{name}.debug.json"
        await self._write_json(debug_path, payload)

    async def try_acquire_lock(
        self, name: str, owner: str, ttl_seconds: int
    ) -> tuple[LockLease | None, LockLease | None]:
        """Attempt to acquire a lock. Returns (lease, existing)."""

        return await anyio.to_thread.run_sync(self._try_acquire_lock_sync, name, owner, ttl_seconds)

    async def release_lock(self, lease: LockLease) -> None:
        """Release a previously acquired lock if still owned by the lease holder."""

        await anyio.to_thread.run_sync(self._release_lock_sync, lease)

    async def break_lock(self, name: str) -> None:
        """Forcefully remove a lock file without validating the owner."""

        await anyio.to_thread.run_sync(self._break_lock_sync, name)

    def _cleanup_legacy_sync(self) -> None:
        for legacy_dir in self.tenant_root.glob("sync-meta-*"):
            shutil.rmtree(legacy_dir, ignore_errors=True)

        metadata_mirror = self.tenant_root / PathBuilder.METADATA_DIR
        if metadata_mirror.exists():
            for legacy_dir in metadata_mirror.glob("sync-meta-*"):
                shutil.rmtree(legacy_dir, ignore_errors=True)

    def _url_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()
        return self._key_path(f"url_{digest}")

    def _key_path(self, key: str) -> Path:
        return self.metadata_root / f"{key}.json"

    def _lock_path(self, name: str) -> Path:
        safe = name.replace("/", "_")
        return self._locks_root / f"{safe}.lock"

    async def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        async with await anyio.open_file(tmp_path, "w", encoding="utf-8") as fp:
            await fp.write(json.dumps(payload, indent=2, sort_keys=True))
        await anyio.to_thread.run_sync(shutil.move, str(tmp_path), str(path))

    async def _read_json(self, path: Path) -> dict | None:
        try:
            async with await anyio.open_file(path, "r", encoding="utf-8") as fp:
                content = await fp.read()
            return json.loads(content)
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as err:
            logger.debug("Failed to read metadata file %s: %s", path, err)
            return None

    def _try_acquire_lock_sync(
        self, name: str, owner: str, ttl_seconds: int
    ) -> tuple[LockLease | None, LockLease | None]:
        path = self._lock_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)
        payload = {
            "name": name,
            "owner": owner,
            "acquired_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            existing = self._read_lock_sync(name, path)
            return None, existing

        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)

        lease = LockLease(name=name, owner=owner, acquired_at=now, expires_at=expires_at, path=path)
        return lease, None

    def _release_lock_sync(self, lease: LockLease) -> None:
        path = lease.path
        existing = self._read_lock_sync(lease.name, path)
        if existing and existing.owner != lease.owner:
            logger.debug("Skipping release for lock %s owned by %s", lease.name, existing.owner)
            return
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError as err:
            logger.warning("Failed to release lock %s: %s", lease.name, err)

    def _break_lock_sync(self, name: str) -> None:
        path = self._lock_path(name)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError as err:
            logger.warning("Failed to break lock %s: %s", name, err)

    def _read_lock_sync(self, name: str, path: Path) -> LockLease | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError as err:
            logger.warning("Lock file %s is corrupt: %s", path, err)
            return None

        try:
            acquired_at = datetime.fromisoformat(payload["acquired_at"])
            expires_at = datetime.fromisoformat(payload["expires_at"])
        except (KeyError, ValueError) as err:
            logger.warning("Lock file %s missing timestamps: %s", path, err)
            return None

        return LockLease(
            name=payload.get("name", name),
            owner=payload.get("owner", "unknown"),
            acquired_at=acquired_at,
            expires_at=expires_at,
            path=path,
        )
