"""Shared lifecycle primitives for crawler and git schedulers."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from contextlib import suppress
from datetime import datetime, timezone
import logging
from typing import Any

from cron_converter import Cron

from .scheduler_protocol import SyncSchedulerProtocol


logger = logging.getLogger(__name__)


class BaseSchedulerService(SyncSchedulerProtocol, ABC):
    """Provide common lifecycle/state management for scheduler services."""

    def __init__(
        self,
        *,
        mode: str,
        refresh_schedule: str | None = None,
        enabled: bool = True,
        run_triggers_in_background: bool = True,
        manage_cron_loop: bool = True,
    ) -> None:
        self.mode = mode
        self.refresh_schedule = refresh_schedule
        self.enabled = enabled
        self._run_triggers_in_background = run_triggers_in_background
        self._manage_cron_loop = manage_cron_loop and bool(refresh_schedule)
        self._cron = self._build_cron(refresh_schedule) if self._manage_cron_loop else None

        self._initialized = False
        self._running = False
        self._active_trigger_task: asyncio.Task | None = None
        self._scheduler_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

        self._total_syncs = 0
        self._errors = 0
        self._last_sync_at: datetime | None = None
        self._next_sync_at: datetime | None = None
        self._last_result: dict[str, Any] | None = None

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def running(self) -> bool:
        if self._manage_cron_loop and self._scheduler_task:
            return self._running and not self._scheduler_task.done()
        return self._running

    @property
    def stats(self) -> dict[str, Any]:
        base_stats: dict[str, Any] = {
            "mode": self.mode,
            "refresh_schedule": self.refresh_schedule,
            "total_syncs": self._total_syncs,
            "last_sync_at": self._datetime_to_iso(self._last_sync_at),
            "next_sync_at": self._datetime_to_iso(self._next_sync_at),
            "errors": self._errors,
            "last_result": self._last_result,
        }
        base_stats.update(self._extra_stats())
        return base_stats

    async def initialize(self) -> bool:
        if self.is_initialized:
            return True
        if not self.enabled:
            logger.debug("Scheduler disabled; skipping initialization")
            return False

        success = await self._initialize_impl()
        if not success:
            return False

        self._initialized = True
        if self._manage_cron_loop and self._cron:
            self._start_scheduler_loop()
        return True

    async def stop(self) -> None:
        if self._manage_cron_loop:
            self._stop_event.set()
            if self._scheduler_task is not None:
                self._scheduler_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._scheduler_task
                self._scheduler_task = None

        if self._active_trigger_task is not None:
            self._active_trigger_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._active_trigger_task
            self._active_trigger_task = None

        await self._stop_impl()
        self._running = False
        self._initialized = False

    async def trigger_sync(self, *, force_crawler: bool = False, force_full_sync: bool = False) -> dict:
        if not self.is_initialized:
            return {"success": False, "message": "Scheduler not initialized"}

        if self._run_triggers_in_background:
            if self._active_trigger_task and not self._active_trigger_task.done():
                return {"success": False, "message": "Sync already running"}

            task = asyncio.create_task(
                self._execute_and_record(force_crawler=force_crawler, force_full_sync=force_full_sync)
            )
            self._active_trigger_task = task
            task.add_done_callback(self._on_background_sync_complete)
            return {"success": True, "message": "Sync trigger accepted (running asynchronously)"}

        return await self._execute_and_record(force_crawler=force_crawler, force_full_sync=force_full_sync)

    async def get_status_snapshot(self) -> dict:
        stats_payload = await self._build_status_payload()
        return {
            "scheduler_running": self.running,
            "scheduler_initialized": self.is_initialized,
            "stats": stats_payload,
        }

    async def _build_status_payload(self) -> dict[str, Any]:
        return self.stats

    def _build_cron(self, schedule: str | None) -> Cron | None:
        if not schedule:
            return None
        try:
            return Cron(schedule)
        except Exception as exc:  # pragma: no cover - invalid config should fail fast
            logger.error("Invalid cron schedule '%s': %s", schedule, exc)
            raise

    def _start_scheduler_loop(self) -> None:
        if not self._cron:
            return
        if self._scheduler_task and not self._scheduler_task.done():
            return

        self._stop_event.clear()
        self._running = True
        self._scheduler_task = asyncio.create_task(self._run_scheduler_loop())

    async def _run_scheduler_loop(self) -> None:
        assert self._cron is not None

        consecutive_failures = 0
        base_retry_delay = 60
        max_retry_delay = 3600

        try:
            while not self._stop_event.is_set():
                now = datetime.now(timezone.utc)
                schedule = self._cron.schedule(start_date=self._last_sync_at or now)
                next_run = schedule.next()
                self._next_sync_at = next_run

                wait_seconds = max(0.0, min((next_run - now).total_seconds(), 60.0))
                if wait_seconds > 0:
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
                        break
                    except asyncio.TimeoutError:
                        pass

                result = await self._execute_and_record(force_crawler=False, force_full_sync=False)
                if result.get("success"):
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    delay = min(base_retry_delay * (2 ** (consecutive_failures - 1)), max_retry_delay)
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                        break
                    except asyncio.TimeoutError:
                        continue
        except asyncio.CancelledError:  # pragma: no cover - cooperative cancellation
            raise
        except Exception:  # pragma: no cover - defensive logging
            logger.error("Scheduler loop failed", exc_info=True)
        finally:
            self._running = False

    def _schedule_interval_hours(self) -> float | None:
        if not self._cron:
            return None
        try:
            now = datetime.now(timezone.utc)
            schedule = self._cron.schedule(start_date=self._last_sync_at or now)
            next_run = schedule.next()
            return (next_run - now).total_seconds() / 3600
        except Exception:  # pragma: no cover - defensive logging
            return None

    async def _execute_and_record(self, *, force_crawler: bool, force_full_sync: bool) -> dict:
        try:
            result = await self._execute_sync_impl(
                force_crawler=force_crawler,
                force_full_sync=force_full_sync,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Scheduler sync failed: %s", exc, exc_info=True)
            result = {"success": False, "message": f"Scheduler sync error: {exc}"}

        self._record_result(result)
        return result

    def _record_result(self, result: dict) -> None:
        if not isinstance(result, dict):
            self._errors += 1
            return

        if result.get("success"):
            self._total_syncs += 1
            self._last_sync_at = datetime.now(timezone.utc)
            payload = self._result_payload_from_sync_result(result)
            self._last_result = payload or result
            if self._cron:
                try:
                    schedule = self._cron.schedule(start_date=self._last_sync_at)
                    self._next_sync_at = schedule.next()
                except Exception:  # pragma: no cover - defensive logging
                    self._next_sync_at = None
        else:
            self._errors += 1

    def _on_background_sync_complete(self, task: asyncio.Task) -> None:
        if self._active_trigger_task is task:
            self._active_trigger_task = None
        with suppress(asyncio.CancelledError):
            task.result()

    def _datetime_to_iso(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    def _extra_stats(self) -> dict[str, Any]:
        return {}

    def _result_payload_from_sync_result(self, result: dict[str, Any]) -> dict[str, Any] | None:
        return result

    @abstractmethod
    async def _initialize_impl(self) -> bool:
        """Perform scheduler-specific initialization."""

    @abstractmethod
    async def _stop_impl(self) -> None:
        """Stop scheduler-specific resources."""

    @abstractmethod
    async def _execute_sync_impl(self, *, force_crawler: bool, force_full_sync: bool) -> dict:
        """Execute a single sync run."""
