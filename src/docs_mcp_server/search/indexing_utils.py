"""Shared helpers for building tenant indexing contexts."""

from __future__ import annotations

from pathlib import Path

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.search.indexer import TenantIndexingContext
from docs_mcp_server.search.schema import Schema, SchemaField, TextField, create_default_schema


DEFAULT_SEGMENTS_SUBDIR = "__search_segments"


def resolve_docs_root(tenant: TenantConfig) -> Path:
    base = tenant.docs_root_dir or Path("mcp-data") / tenant.codename
    path = Path(base).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"docs_root_dir missing: {path}")
    return path.resolve()


def resolve_segments_dir(
    docs_root: Path,
    tenant_codename: str,
    *,
    segments_root: Path | None,
    segments_subdir: str = DEFAULT_SEGMENTS_SUBDIR,
) -> Path:
    path = (segments_root.expanduser() / tenant_codename).resolve() if segments_root else docs_root / segments_subdir
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_schema_for_tenant(tenant: TenantConfig) -> Schema:
    base = create_default_schema()
    analyzer_name = _analyzer_for_profile(tenant.search.analyzer_profile)
    if analyzer_name is None:
        return base

    fields: list[SchemaField] = []
    for field in base.fields:
        if isinstance(field, TextField):
            fields.append(
                TextField(
                    name=field.name,
                    stored=field.stored,
                    indexed=field.indexed,
                    boost=field.boost,
                    analyzer_name=analyzer_name,
                )
            )
        else:
            fields.append(field)

    return Schema(fields=fields, unique_field=base.unique_field, name=base.name)


def build_indexing_context(
    tenant: TenantConfig,
    *,
    segments_root: Path | None = None,
    segments_subdir: str = DEFAULT_SEGMENTS_SUBDIR,
    use_sqlite_storage: bool = False,
) -> TenantIndexingContext:
    docs_root = resolve_docs_root(tenant)
    segments_dir = resolve_segments_dir(
        docs_root,
        tenant.codename,
        segments_root=segments_root,
        segments_subdir=segments_subdir,
    )
    schema = build_schema_for_tenant(tenant)
    return TenantIndexingContext(
        codename=tenant.codename,
        docs_root=docs_root,
        segments_dir=segments_dir,
        source_type=tenant.source_type,
        schema=schema,
        url_whitelist_prefixes=tuple(tenant.get_url_whitelist_prefixes()),
        url_blacklist_prefixes=tuple(tenant.get_url_blacklist_prefixes()),
        use_sqlite_storage=use_sqlite_storage,
    )


def _analyzer_for_profile(profile: str) -> str | None:
    mapping = {
        "default": None,
        "aggressive-stem": "aggressive-stem",
        "code-friendly": "code-friendly",
    }
    return mapping.get(profile)
