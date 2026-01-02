"""Shared interface for crawler and git schedulers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SyncSchedulerProtocol(Protocol):
    """Common scheduler surface consumed by HTTP endpoints and workers."""

    @property
    def is_initialized(self) -> bool:  # pragma: no cover - Protocol only
        """Return True once scheduler finished its initial sync/bootstrap."""

    @property
    def running(self) -> bool:  # pragma: no cover - Protocol only
        """Return True while a background scheduler loop is active."""

    @property
    def stats(self) -> dict[str, object]:  # pragma: no cover - Protocol only
        """Return scheduler-specific metrics suitable for status endpoints."""

    async def initialize(self) -> bool:  # pragma: no cover - Protocol only
        """Start the scheduler (and perform initial sync if needed)."""

    async def stop(self) -> None:  # pragma: no cover - Protocol only
        """Stop the scheduler and release resources."""

    async def trigger_sync(  # pragma: no cover - Protocol only
        self,
        *,
        force_crawler: bool = False,
        force_full_sync: bool = False,
    ) -> dict:
        """Trigger an immediate sync attempt and return structured status."""
