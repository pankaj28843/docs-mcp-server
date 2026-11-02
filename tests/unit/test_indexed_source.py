"""Generation-bound source evidence."""

import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from docs_mcp_server.deployment_config import IndexedSource, TenantConfig
from docs_mcp_server.search.indexer import TenantIndexer
from docs_mcp_server.search.indexing_utils import build_indexing_context


@pytest.mark.parametrize(
    "changes",
    [
        {"canonical_url": "file:///local/path"},
        {"canonical_url": "https://user:secret@example.com/"},
        {"canonical_url": "https://example.com:bad/"},
        {"version": None},
        {"version": "  "},
        {"evidence_url": None},
        {"evidence_url": "https://user:secret@example.com/"},
        {"version_kind": "current"},
    ],
)
def test_invalid_source_claims_are_rejected(changes: dict) -> None:
    source = {
        "canonical_url": "https://docs.djangoproject.com/en/5.2/",
        "version_kind": "versioned",
        "version": "5.2",
        "evidence_url": "https://docs.djangoproject.com/en/5.2/",
    }
    with pytest.raises(ValidationError):
        IndexedSource.model_validate(source | changes)


@pytest.mark.parametrize("kind", ["unversioned", "current", "unknown"])
def test_nonversioned_sources_have_no_version(kind: str) -> None:
    source = IndexedSource(
        canonical_url="https://example.com/docs/",
        version_kind=kind,
        evidence_url=None if kind == "unknown" else "https://example.com/docs/",
    )
    assert source.version is None


def test_source_evidence_is_captured_only_when_generation_is_built(tmp_path: Path) -> None:
    (tmp_path / "page.md").write_text("# A document\n\nContent", encoding="utf-8")
    config = TenantConfig(
        codename="example",
        docs_name="Example",
        source_type="filesystem",
        docs_root_dir=str(tmp_path),
        indexed_source=IndexedSource(
            canonical_url="https://docs.djangoproject.com/en/5.2/",
            version_kind="versioned",
            version="5.2",
            evidence_url="https://docs.djangoproject.com/en/5.2/?lang=en#versions",
        ),
    )
    context = build_indexing_context(config)
    indexer = TenantIndexer(context)
    indexer.build_segment()
    manifest_path = context.segments_dir / "manifest.json"
    original = json.loads(manifest_path.read_text())
    assert original["provenance"]["indexed_source"] == config.indexed_source.model_dump()

    changed = config.model_copy(update={"indexed_source": config.indexed_source.model_copy(update={"version": "6.1"})})
    new_indexer = TenantIndexer(build_indexing_context(changed))
    assert json.loads(manifest_path.read_text()) == original
    assert new_indexer.fingerprint_audit().needs_rebuild
    new_indexer.build_segment()
    rebuilt = json.loads(manifest_path.read_text())
    assert rebuilt["latest_segment_id"] != original["latest_segment_id"]
    assert rebuilt["provenance"]["indexed_source"]["version"] == "6.1"
