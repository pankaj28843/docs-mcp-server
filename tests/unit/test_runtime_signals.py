"""Tests for runtime signals."""
import asyncio
from unittest.mock import Mock

import pytest

from docs_mcp_server.runtime.signals import install_shutdown_signals


@pytest.mark.unit
def test_install_shutdown_signals():
    """Test install_shutdown_signals creates event."""
    app = Mock()
    app.state.shutdown_event = None
    
    result = install_shutdown_signals(app)
    assert isinstance(result, asyncio.Event)
