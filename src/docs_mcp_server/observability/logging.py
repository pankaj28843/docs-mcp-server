"""Structured JSON logging with trace correlation."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import sys
from typing import Any

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter as GrpcOTLPLogExporter
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter as HttpOTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
import orjson

from docs_mcp_server.deployment_config import ObservabilityCollectorConfig
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

        return orjson.dumps(log_entry, default=self._json_default).decode("utf-8")

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

    def _json_default(self, value: Any) -> Any:
        if isinstance(value, set):
            try:
                return sorted(value)
            except TypeError:
                return list(value)
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, Exception):
            return str(value)
        return repr(value)


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


_logger_holder: dict[str, object] = {"provider": None, "handler_added": False}


def init_log_exporter(
    service_name: str = "docs-mcp-server",
    resource_attributes: dict[str, str] | None = None,
) -> LoggerProvider:
    attributes = {"service.name": service_name}
    if resource_attributes:
        attributes.update(resource_attributes)
    resource = Resource.create(attributes)
    provider = LoggerProvider(resource=resource)
    set_logger_provider(provider)
    _logger_holder["provider"] = provider
    return provider


def configure_log_exporter(
    config: ObservabilityCollectorConfig | None,
    provider: LoggerProvider | None = None,
) -> None:
    if not config or not config.enabled:
        return

    active_provider = provider or _logger_holder.get("provider")
    if not isinstance(active_provider, LoggerProvider):
        active_provider = init_log_exporter()

    endpoint = config.collector_endpoint
    if config.otlp_protocol == "http" and endpoint.endswith("/v1/traces"):
        endpoint = endpoint.removesuffix("/v1/traces") + "/v1/logs"

    if config.otlp_protocol == "grpc":
        exporter = GrpcOTLPLogExporter(
            endpoint=endpoint,
            headers=config.headers,
            timeout=config.timeout_seconds,
            insecure=config.grpc_insecure,
        )
    else:
        exporter = HttpOTLPLogExporter(
            endpoint=endpoint,
            headers=config.headers,
            timeout=config.timeout_seconds,
        )

    if _logger_holder.get("handler_added"):
        return

    active_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    handler = LoggingHandler(level=logging.INFO, logger_provider=active_provider)
    logging.getLogger().addHandler(handler)
    _logger_holder["handler_added"] = True
