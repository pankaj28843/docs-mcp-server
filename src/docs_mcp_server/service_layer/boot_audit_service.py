import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
import logging
import os
from pathlib import Path
import sys
import time
from typing import Literal


logger = logging.getLogger(__name__)

_TRUTHY_VALUES = {"1", "true", "yes", "on"}


@dataclass(slots=True)
class BootAuditStatus:
    state: Literal["pending", "running", "succeeded", "failed", "skipped", "cancelled"]
    total_tenants: int
    completed_tenants: int
    started_at: float | None
    finished_at: float | None
    exit_code: int | None
    error: str | None
    skip_reason: str | None

    def to_dict(self) -> dict[str, object | None]:
        return asdict(self)


def _is_truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in _TRUTHY_VALUES)


def _resolve_boot_audit_timeout(tenant_count: int) -> int:
    env_timeout = os.getenv("DOCS_BOOT_AUDIT_TIMEOUT")
    if env_timeout:
        try:
            parsed = int(env_timeout)
            if parsed >= 30:
                return parsed
        except ValueError:
            logger.warning("Invalid DOCS_BOOT_AUDIT_TIMEOUT=%s; falling back to default", env_timeout)
    return max(60, 300 * max(1, tenant_count))


def _log_subprocess_stream(payload: bytes | None, *, prefix: str, level: int) -> None:
    if not payload:
        return
    for line in payload.decode().splitlines():
        logger.log(level, "%s %s", prefix, line)


async def _run_index_audit_subprocess(cmd: list[str], timeout: int) -> int:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=os.environ.copy(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        with suppress(ProcessLookupError):
            await proc.communicate()
        raise

    _log_subprocess_stream(stdout, prefix="[index_audit]", level=logging.INFO)
    stderr_level = logging.ERROR if proc.returncode else logging.INFO
    _log_subprocess_stream(stderr, prefix="[index_audit]", level=stderr_level)
    return proc.returncode


class BootAuditService:
    def __init__(
        self,
        *,
        config_path: Path,
        tenant_count: int,
        runner: Callable[[list[str], int], Awaitable[int]] | None = None,
    ) -> None:
        self._config_path = config_path
        self._tenant_count = tenant_count
        self._runner = runner or _run_index_audit_subprocess
        self._timeout = _resolve_boot_audit_timeout(tenant_count)
        self._task: asyncio.Task | None = None
        self.status = BootAuditStatus(
            state="pending",
            total_tenants=tenant_count,
            completed_tenants=0,
            started_at=None,
            finished_at=None,
            exit_code=None,
            error=None,
            skip_reason=None,
        )

    def _should_skip(self) -> str | None:
        if self._tenant_count == 0:
            return "No tenants configured"
        if _is_truthy(os.getenv("DOCS_SKIP_BOOT_AUDIT")):
            return "DOCS_SKIP_BOOT_AUDIT set"
        if not self._config_path.exists():
            return f"Config {self._config_path} missing"
        return None

    def schedule(self) -> asyncio.Task | None:
        if self._task is not None:
            return self._task

        skip_reason = self._should_skip()
        if skip_reason:
            self.status.state = "skipped"
            self.status.skip_reason = skip_reason
            return None

        self.status.state = "running"
        self.status.started_at = time.time()
        self._task = asyncio.create_task(self._run())
        return self._task

    async def _run(self) -> None:
        try:
            cmd = [
                sys.executable,
                "-m",
                "docs_mcp_server.index_audit",
                "--config",
                str(self._config_path),
                "--rebuild",
            ]
            logger.info(
                "Running boot-time index audit in background for %d tenant(s) (timeout=%ss)",
                self._tenant_count,
                self._timeout,
            )
            exit_code = await self._runner(cmd, self._timeout)
            self.status.exit_code = exit_code
            self.status.completed_tenants = self._tenant_count
            if exit_code == 0:
                self.status.state = "succeeded"
                logger.info("Boot-time index audit complete")
            else:
                self.status.state = "failed"
                self.status.error = f"Exit code {exit_code}"
                logger.error("Boot-time index audit exited with code %s", exit_code)
        except asyncio.TimeoutError:
            self.status.state = "failed"
            self.status.error = f"Timed out after {self._timeout}s"
            logger.error("Boot-time index audit timed out after %ss", self._timeout)
        except Exception as exc:  # pragma: no cover - defensive
            self.status.state = "failed"
            self.status.error = str(exc)
            logger.error("Boot-time index audit failed: %s", exc, exc_info=True)
        finally:
            self.status.finished_at = time.time()
            self._task = None

    def cancel(self) -> None:
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        self.status.state = "cancelled"
        self.status.finished_at = time.time()

    def is_running(self) -> bool:
        return self._task is not None

    def get_status(self) -> BootAuditStatus:
        return self.status
