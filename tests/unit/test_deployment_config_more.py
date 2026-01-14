"""Additional unit tests for deployment config helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docs_mcp_server.deployment_config import DeploymentConfig, TenantConfig, _normalize_url_collection


@pytest.mark.unit
def test_normalize_url_collection_skips_none_items():
    assert _normalize_url_collection([None, "https://example.com"]) == ["https://example.com"]


@pytest.mark.unit
def test_normalize_url_collection_rejects_invalid_type():
    with pytest.raises(TypeError):
        _normalize_url_collection(123)


@pytest.mark.unit
def test_tenant_docs_sync_enabled_property():
    tenant = TenantConfig(
        source_type="online",
        codename="docs",
        docs_name="Docs",
        refresh_schedule="0 0 * * *",
        docs_entry_url=["https://example.com/"],
    )

    assert tenant.docs_sync_enabled is True


@pytest.mark.unit
def test_git_tenant_requires_subpaths():
    with pytest.raises(ValueError, match="git_subpaths"):
        TenantConfig(
            source_type="git",
            codename="git",
            docs_name="Git Docs",
            git_repo_url="https://example.com/repo.git",
            git_subpaths=None,
        )


@pytest.mark.unit
def test_from_json_file_rejects_invalid_operation_mode(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "deployment.json"
    config_path.write_text(
        json.dumps(
            {
                "infrastructure": {"operation_mode": "online"},
                "tenants": [
                    {
                        "source_type": "online",
                        "codename": "docs",
                        "docs_name": "Docs",
                        "docs_entry_url": ["https://example.com/"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("OPERATION_MODE", "invalid")

    with pytest.raises(ValueError, match="Invalid OPERATION_MODE"):
        DeploymentConfig.from_json_file(config_path)
