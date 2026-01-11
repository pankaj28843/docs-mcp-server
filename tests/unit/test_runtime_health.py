"""Tests for runtime health."""
from unittest.mock import Mock

import pytest

from docs_mcp_server.runtime.health import build_health_endpoint


@pytest.mark.unit
def test_build_health_endpoint():
    """Test build_health_endpoint creates endpoint."""
    tenant_apps = []
    infra = Mock()
    
    endpoint = build_health_endpoint(tenant_apps, infra)
    assert callable(endpoint)
