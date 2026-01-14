"""Additional unit tests for tenant registry helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.registry import TenantMetadata, TenantRegistry


@pytest.mark.unit
def test_tenant_metadata_from_config_skips_invalid_urls(monkeypatch):
    config = TenantConfig(
        source_type="online",
        codename="docs",
        docs_name="Docs",
        docs_entry_url=["invalid-url"],
    )
    tenant_app = SimpleNamespace(supports_browse=lambda: False)

    monkeypatch.setattr("docs_mcp_server.registry.urlparse", lambda _url: (_ for _ in ()).throw(ValueError("bad")))

    metadata = TenantMetadata.from_config(config, tenant_app)

    assert metadata.codename == "docs"


@pytest.mark.unit
def test_tenant_registry_get_metadata_missing_returns_none():
    registry = TenantRegistry()

    assert registry.get_metadata("missing") is None
