"""Unit tests for search indexing utility helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.search.indexing_utils import (
    build_indexing_context,
    build_schema_for_tenant,
    resolve_docs_root,
    resolve_segments_dir,
)
from docs_mcp_server.search.schema import TextField, create_default_schema


pytestmark = pytest.mark.unit


def _tenant_with_root(tmp_path: Path, **overrides) -> TenantConfig:
    return TenantConfig(
        source_type="filesystem",
        codename="docs",
        docs_name="Docs",
        docs_root_dir=str(tmp_path),
        **overrides,
    )


def test_resolve_docs_root_expands_and_resolves(tmp_path: Path) -> None:
    tenant = _tenant_with_root(tmp_path)

    resolved = resolve_docs_root(tenant)

    assert resolved == tmp_path.resolve()


def test_resolve_docs_root_raises_for_missing_path(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing"
    tenant = _tenant_with_root(missing_path)

    with pytest.raises(FileNotFoundError):
        resolve_docs_root(tenant)


def test_resolve_segments_dir_uses_root_override(tmp_path: Path) -> None:
    segments_root = tmp_path / "segments"
    docs_root = tmp_path / "docs"
    docs_root.mkdir()

    result = resolve_segments_dir(docs_root, "demo", segments_root=segments_root, segments_subdir="ignored")

    assert result == (segments_root / "demo").resolve()
    assert result.is_dir()


def test_build_schema_for_tenant_overrides_analyzer_profile(tmp_path: Path) -> None:
    tenant = _tenant_with_root(tmp_path, search={"analyzer_profile": "code-friendly"})

    schema = build_schema_for_tenant(tenant)

    text_fields = [field for field in schema.fields if isinstance(field, TextField)]
    assert text_fields
    assert all(field.analyzer_name == "code-friendly" for field in text_fields)


def test_build_indexing_context_propagates_url_filters(tmp_path: Path) -> None:
    tenant = _tenant_with_root(
        tmp_path,
        url_whitelist_prefixes="https://docs.example.com/",
        url_blacklist_prefixes="https://docs.example.com/releases/",
    )

    context = build_indexing_context(tenant)

    assert context.docs_root == tmp_path.resolve()
    assert context.url_whitelist_prefixes == ("https://docs.example.com/",)
    assert context.url_blacklist_prefixes == ("https://docs.example.com/releases/",)


def test_build_schema_for_tenant_default_profile_is_unchanged(tmp_path: Path) -> None:
    tenant = _tenant_with_root(tmp_path, search={"analyzer_profile": "default"})

    schema = build_schema_for_tenant(tenant)
    base = create_default_schema()

    base_text = [field for field in base.fields if isinstance(field, TextField)]
    schema_text = [field for field in schema.fields if isinstance(field, TextField)]

    assert [field.analyzer_name for field in schema_text] == [field.analyzer_name for field in base_text]
