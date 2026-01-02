"""Signal handling utilities for graceful Starlette shutdown."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import signal
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from starlette.applications import Starlette


logger = logging.getLogger(__name__)


def install_shutdown_signals(app: Starlette) -> asyncio.Event:
    """Attach SIGINT/SIGTERM handlers that set ``app.state.shutdown_event``.

    The first signal begins graceful shutdown; repeated signals are ignored.
    Returns the event so other code can await it.
    """

    existing = getattr(app.state, "shutdown_event", None)
    if isinstance(existing, asyncio.Event):
        return existing

    shutdown_event = asyncio.Event()

    def _make_handler(sig: signal.Signals) -> Callable[[int, object | None], None]:
        def _handler(signum: int, frame: object | None) -> None:  # pragma: no cover - signal glue
            if shutdown_event.is_set():
                return
            logger.info("Received %s, scheduling shutdown", sig.name)
            shutdown_event.set()

        return _handler

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _make_handler(sig))
        except ValueError:  # pragma: no cover - unsupported in some environments
            logger.debug("Signal %s is not supported in this context", sig.name)

    app.state.shutdown_event = shutdown_event
    return shutdown_event
