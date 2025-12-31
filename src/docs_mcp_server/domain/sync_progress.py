"""Domain model for resilient sync progress tracking.

Implements checkpoint-based resume semantics inspired by:
- Cosmic Python: domain events + aggregates
- Distributed systems: catch-up recovery / checkpoint log
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class SyncProgressError(Exception):
    """Base error for sync progress domain."""


class InvalidPhaseTransitionError(SyncProgressError):
    """Raised when invalid phase transition occurs."""


class SyncPhase(str, Enum):
    """Phases of a sync lifecycle."""

    INITIALIZING = "initializing"
    DISCOVERING = "discovering"
    FETCHING = "fetching"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"

    @property
    def is_terminal(self) -> bool:
        return self in {SyncPhase.COMPLETED, SyncPhase.FAILED}

    @property
    def can_resume(self) -> bool:
        return self in {SyncPhase.DISCOVERING, SyncPhase.FETCHING, SyncPhase.INTERRUPTED}


@dataclass(slots=True, frozen=True)
class SyncStats:
    """Aggregate stats tracked for sync progress."""

    urls_discovered: int = 0
    urls_pending: int = 0
    urls_processed: int = 0
    urls_failed: int = 0
    urls_skipped: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "urls_discovered": self.urls_discovered,
            "urls_pending": self.urls_pending,
            "urls_processed": self.urls_processed,
            "urls_failed": self.urls_failed,
            "urls_skipped": self.urls_skipped,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncStats:
        return cls(
            urls_discovered=int(data.get("urls_discovered", 0)),
            urls_pending=int(data.get("urls_pending", 0)),
            urls_processed=int(data.get("urls_processed", 0)),
            urls_failed=int(data.get("urls_failed", 0)),
            urls_skipped=int(data.get("urls_skipped", 0)),
        )

    def with_updates(
        self,
        *,
        urls_discovered: int | None = None,
        urls_pending: int | None = None,
        urls_processed: int | None = None,
        urls_failed: int | None = None,
        urls_skipped: int | None = None,
    ) -> SyncStats:
        return SyncStats(
            urls_discovered=urls_discovered if urls_discovered is not None else self.urls_discovered,
            urls_pending=urls_pending if urls_pending is not None else self.urls_pending,
            urls_processed=urls_processed if urls_processed is not None else self.urls_processed,
            urls_failed=urls_failed if urls_failed is not None else self.urls_failed,
            urls_skipped=urls_skipped if urls_skipped is not None else self.urls_skipped,
        )


@dataclass(slots=True, frozen=True)
class FailureInfo:
    """Details for a failed URL fetch."""

    url: str
    error_type: str
    error_message: str
    failed_at: datetime
    retry_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "failed_at": self.failed_at.isoformat(),
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FailureInfo:
        failed_at = datetime.fromisoformat(data["failed_at"]).astimezone(timezone.utc)
        return cls(
            url=data["url"],
            error_type=data.get("error_type", "UnknownError"),
            error_message=data.get("error_message", ""),
            failed_at=failed_at,
            retry_count=int(data.get("retry_count", 0)),
        )


# --- Domain Events (Cosmic Python pattern) ---


@dataclass(slots=True)
class SyncEvent:
    sync_id: UUID
    tenant_codename: str
    occurred_at: datetime


@dataclass(slots=True)
class SyncStarted(SyncEvent):
    pass


@dataclass(slots=True)
class PhaseChanged(SyncEvent):
    previous_phase: str
    new_phase: str


@dataclass(slots=True)
class SyncCompleted(SyncEvent):
    pass


@dataclass(slots=True)
class SyncFailed(SyncEvent):
    reason: str


@dataclass(slots=True)
class UrlProcessed(SyncEvent):
    url: str


@dataclass(slots=True)
class UrlFailed(SyncEvent):
    url: str
    error_type: str


@dataclass(slots=True)
class UrlSkipped(SyncEvent):
    url: str
    reason: str


@dataclass
class SyncProgress:
    """Aggregate root for sync progress state machine."""

    tenant_codename: str
    sync_id: UUID
    phase: SyncPhase
    started_at: datetime
    last_checkpoint_at: datetime | None = None
    completed_at: datetime | None = None
    failure_reason: str | None = None
    discovered_urls: set[str] = field(default_factory=set)
    pending_urls: set[str] = field(default_factory=set)
    processed_urls: set[str] = field(default_factory=set)
    failed_urls: dict[str, FailureInfo] = field(default_factory=dict)
    stats: SyncStats = field(default_factory=SyncStats)
    events: list[SyncEvent] = field(default_factory=list)

    @classmethod
    def create_new(cls, tenant_codename: str, sync_id: UUID | None = None) -> SyncProgress:
        sync_id = sync_id or uuid4()
        now = datetime.now(timezone.utc)
        progress = cls(
            tenant_codename=tenant_codename,
            sync_id=sync_id,
            phase=SyncPhase.INITIALIZING,
            started_at=now,
        )
        progress._record_event(SyncStarted(sync_id=sync_id, tenant_codename=tenant_codename, occurred_at=now))
        return progress

    @classmethod
    def restore_from_checkpoint(cls, checkpoint: dict[str, Any]) -> SyncProgress:
        sync_id = UUID(checkpoint["sync_id"])
        phase = SyncPhase(checkpoint["phase"])
        started_at = datetime.fromisoformat(checkpoint["started_at"]).astimezone(timezone.utc)
        last_checkpoint = checkpoint.get("last_checkpoint_at")
        last_checkpoint_at = (
            datetime.fromisoformat(last_checkpoint).astimezone(timezone.utc) if last_checkpoint else None
        )
        completed_at = checkpoint.get("completed_at")
        progress = cls(
            tenant_codename=checkpoint["tenant_codename"],
            sync_id=sync_id,
            phase=phase,
            started_at=started_at,
            last_checkpoint_at=last_checkpoint_at,
            completed_at=(datetime.fromisoformat(completed_at).astimezone(timezone.utc) if completed_at else None),
            failure_reason=checkpoint.get("failure_reason"),
            discovered_urls=set(checkpoint.get("discovered_urls", [])),
            pending_urls=set(checkpoint.get("pending_urls", [])),
            processed_urls=set(checkpoint.get("processed_urls", [])),
            failed_urls={url: FailureInfo.from_dict(info) for url, info in checkpoint.get("failed_urls", {}).items()},
            stats=SyncStats.from_dict(checkpoint.get("stats", {})),
        )
        return progress

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncProgress:
        return cls.restore_from_checkpoint(data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sync_id": str(self.sync_id),
            "tenant_codename": self.tenant_codename,
            "phase": self.phase.value,
            "started_at": self.started_at.isoformat(),
            "last_checkpoint_at": self.last_checkpoint_at.isoformat() if self.last_checkpoint_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "failure_reason": self.failure_reason,
            "discovered_urls": sorted(self.discovered_urls),
            "pending_urls": sorted(self.pending_urls),
            "processed_urls": sorted(self.processed_urls),
            "failed_urls": {url: info.to_dict() for url, info in self.failed_urls.items()},
            "stats": self.stats.to_dict(),
        }

    def create_checkpoint(self) -> dict[str, Any]:
        self.last_checkpoint_at = datetime.now(timezone.utc)
        return self.to_dict()

    def start_discovery(self) -> None:
        self._transition_to(SyncPhase.DISCOVERING)

    def start_fetching(self) -> None:
        self._transition_to(SyncPhase.FETCHING)

    def mark_completed(self) -> None:
        self._transition_to(SyncPhase.COMPLETED)
        self.completed_at = datetime.now(timezone.utc)
        self._record_event(
            SyncCompleted(sync_id=self.sync_id, tenant_codename=self.tenant_codename, occurred_at=self.completed_at)
        )

    def mark_failed(self, *, error: str) -> None:
        self.failure_reason = error
        self._transition_to(SyncPhase.FAILED)
        now = datetime.now(timezone.utc)
        self._record_event(
            SyncFailed(sync_id=self.sync_id, tenant_codename=self.tenant_codename, occurred_at=now, reason=error)
        )

    def resume(self) -> None:
        if not self.phase.can_resume:
            raise InvalidPhaseTransitionError(f"Cannot resume from phase {self.phase}")
        self._transition_to(SyncPhase.FETCHING)

    def add_discovered_urls(self, urls: Iterable[str]) -> None:
        new_urls = set(urls) - self.discovered_urls
        if not new_urls:
            return
        self.discovered_urls.update(new_urls)
        self.pending_urls.update(new_urls)
        self.stats = self.stats.with_updates(
            urls_discovered=len(self.discovered_urls),
            urls_pending=len(self.pending_urls),
        )

    def enqueue_urls(self, urls: Iterable[str]) -> None:
        added = False
        for url in urls:
            if url in self.processed_urls:
                continue
            if url not in self.pending_urls:
                self.pending_urls.add(url)
                added = True
        if added:
            self.stats = self.stats.with_updates(urls_pending=len(self.pending_urls))

    def mark_url_processed(self, url: str) -> None:
        if url in self.pending_urls:
            self.pending_urls.remove(url)
        self.processed_urls.add(url)
        self.failed_urls.pop(url, None)
        self.stats = self.stats.with_updates(
            urls_pending=len(self.pending_urls),
            urls_processed=len(self.processed_urls),
            urls_failed=len(self.failed_urls),
        )
        self._record_event(
            UrlProcessed(
                sync_id=self.sync_id,
                tenant_codename=self.tenant_codename,
                occurred_at=datetime.now(timezone.utc),
                url=url,
            )
        )

    def mark_url_failed(self, *, url: str, error_type: str, error_message: str) -> None:
        now = datetime.now(timezone.utc)
        previous = self.failed_urls.get(url)
        retry_count = previous.retry_count + 1 if previous else 1
        info = FailureInfo(
            url=url, error_type=error_type, error_message=error_message, failed_at=now, retry_count=retry_count
        )
        self.failed_urls[url] = info
        self.pending_urls.discard(url)
        self.processed_urls.discard(url)
        self.stats = self.stats.with_updates(
            urls_pending=len(self.pending_urls),
            urls_processed=len(self.processed_urls),
            urls_failed=len(self.failed_urls),
        )
        self._record_event(
            UrlFailed(
                sync_id=self.sync_id,
                tenant_codename=self.tenant_codename,
                occurred_at=now,
                url=url,
                error_type=error_type,
            )
        )

    def mark_url_skipped(self, url: str, reason: str) -> None:
        self.pending_urls.discard(url)
        self.stats = self.stats.with_updates(
            urls_pending=len(self.pending_urls), urls_skipped=self.stats.urls_skipped + 1
        )
        self._record_event(
            UrlSkipped(
                sync_id=self.sync_id,
                tenant_codename=self.tenant_codename,
                occurred_at=datetime.now(timezone.utc),
                url=url,
                reason=reason,
            )
        )

    @property
    def can_resume(self) -> bool:
        return self.phase.can_resume

    @property
    def is_complete(self) -> bool:
        return self.phase == SyncPhase.COMPLETED

    @property
    def duration(self) -> timedelta | None:
        end_time = self.completed_at or datetime.now(timezone.utc)
        return end_time - self.started_at

    def _transition_to(self, new_phase: SyncPhase) -> None:
        if self.phase == new_phase:
            return
        if self.phase.is_terminal and new_phase != self.phase:
            raise InvalidPhaseTransitionError(f"Cannot transition from terminal phase {self.phase} to {new_phase}")
        previous = self.phase
        self.phase = new_phase
        self._record_event(
            PhaseChanged(
                sync_id=self.sync_id,
                tenant_codename=self.tenant_codename,
                occurred_at=datetime.now(timezone.utc),
                previous_phase=previous.value,
                new_phase=new_phase.value,
            )
        )

    def _record_event(self, event: SyncEvent) -> None:
        self.events.append(event)
