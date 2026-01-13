"""Structured JSON logging with trace correlation."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import sys
from typing import Any

import orjson

from docs_mcp_server.observability.context import get_trace_context


class JsonFormatter(logging.Formatter):
    """JSON formatter with OpenTelemetry trace correlation."""

    REDACT_KEYS = frozenset({"password", "token", "api_key", "secret", "authorization"})
    MAX_MESSAGE_LEN = 2000

    def format(self, record: logging.LogRecord) -> str:
        ctx = get_trace_context()
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": self._truncate(record.getMessage()),
            "logger": record.name,
            "trace_id": ctx.get("trace_id", ""),
            "span_id": ctx.get("span_id", ""),
        }

        # Add component from logger name
        if "." in record.name:
            log_entry["component"] = record.name.split(".")[-1]

        # Add tenant if in context
        if tenant := ctx.get("tenant"):
            log_entry["tenant"] = tenant

        # Add exception info
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add extra fields (redacted)
        if hasattr(record, "__dict__"):
            for key, value in record.__dict__.items():
                if key not in logging.LogRecord.__dict__ and not key.startswith("_"):
                    log_entry[key] = self._redact(key, value)

        return orjson.dumps(log_entry).decode("utf-8")

    def _truncate(self, msg: str) -> str:
        if len(msg) > self.MAX_MESSAGE_LEN:
            return msg[: self.MAX_MESSAGE_LEN] + "..."
        return msg

    def _redact(self, key: str, value: Any) -> Any:
        if key.lower() in self.REDACT_KEYS:
            return "[REDACTED]"
        if isinstance(value, str) and len(value) > 500:
            return value[:500] + "..."
        return value


def configure_logging(
    level: str = "INFO",
    json_output: bool = True,
    *,
    logger_levels: dict[str, str] | None = None,
    trace_categories: list[str] | None = None,
    trace_level: str = "debug",
    access_log: bool = False,
) -> None:
    """Configure root logger with structured JSON output and per-logger overrides.

    Args:
        level: Root log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_output: Emit structured JSON logs when True
        logger_levels: Per-logger level overrides (logger name -> level string)
        trace_categories: Logger names to set at trace_level for deep debugging
        trace_level: Level applied to trace_categories loggers
        access_log: Enable uvicorn.access logger (otherwise set to WARNING)
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))

    root.addHandler(handler)

    # Reduce noise from third-party libraries by default
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    # Control uvicorn access logs
    if not access_log:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # Apply trace_categories at trace_level
    resolved_trace = getattr(logging, trace_level.upper(), logging.DEBUG)
    for category in trace_categories or []:
        logging.getLogger(category).setLevel(resolved_trace)

    # Apply per-logger overrides (these take precedence over trace_categories)
    for logger_name, logger_level in (logger_levels or {}).items():
        resolved = getattr(logging, logger_level.upper(), logging.INFO)
        logging.getLogger(logger_name).setLevel(resolved)
