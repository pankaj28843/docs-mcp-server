"""Additional unit tests for tenant helpers and edge cases."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from docs_mcp_server.deployment_config import ArticleExtractorFallbackConfig, SharedInfraConfig, TenantConfig
from docs_mcp_server.service_layer.filesystem_unit_of_work import FileSystemUnitOfWork
from docs_mcp_server.services.git_sync_scheduler_service import GitSyncSchedulerService
from docs_mcp_server.tenant import (
    TenantApp,
    TenantSyncRuntime,
    _build_scheduler_service,
    _build_settings,
    _resolve_docs_root,
    _should_autostart_scheduler,
)


def _make_filesystem_config(tmp_path: Path, codename: str = "tenant") -> TenantConfig:
    docs_root = tmp_path / "mcp-data" / codename
    docs_root.mkdir(parents=True)
    return TenantConfig(
        source_type="filesystem",
        codename=codename,
        docs_name="Test Docs",
        docs_root_dir=str(docs_root),
        docs_entry_url=["https://example.com/"],
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tenant_sync_runtime_autostart_calls_initialize(monkeypatch, tmp_path: Path):
    tenant = _make_filesystem_config(tmp_path)
    init_mock = AsyncMock()
    monkeypatch.setattr(
        "docs_mcp_server.tenant._build_scheduler_service", lambda _cfg, _cb=None: SimpleNamespace(initialize=init_mock)
    )
    monkeypatch.setattr("docs_mcp_server.tenant._should_autostart_scheduler", lambda _cfg: True)

    runtime = TenantSyncRuntime(tenant)
    await runtime.initialize()

    init_mock.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_local_file_handles_read_error(tmp_path: Path, monkeypatch):
    tenant = _make_filesystem_config(tmp_path)
    app = TenantApp(tenant)
    file_path = Path(tmp_path / "doc.md")
    file_path.write_text("content", encoding="utf-8")

    async def _raise(*_args, **_kwargs):
        raise OSError("boom")

    monkeypatch.setattr(Path, "read_text", _raise)
    response = await app._fetch_local_file(f"file://{file_path}", context=None)

    assert response.error.startswith("Error reading file")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_cached_truncates_surrounding_context(tmp_path: Path):
    """Test that cached fetch truncates content for surrounding context."""
    tenant = _make_filesystem_config(tmp_path)
    app = TenantApp(tenant)

    # Create cached content in path-based format under docs_root
    docs_root = Path(tenant.docs_root_dir)
    cached_dir = docs_root / "example.com" / "docs"
    cached_dir.mkdir(parents=True)
    cached_file = cached_dir / "doc.md"
    cached_file.write_text("# Title\n\n" + "a" * 9000)

    response = await app.fetch("https://example.com/docs/doc", context="surrounding")

    assert response.error is None
    assert response.content.endswith("...")
    assert len(response.content) == 8003


@pytest.mark.unit
@pytest.mark.asyncio
async def test_browse_tree_uses_relative_root(tmp_path: Path, monkeypatch):
    tenant = _make_filesystem_config(tmp_path, codename="rel")
    tenant.docs_root_dir = "relative-root"
    base_dir = tmp_path / "relative-root"
    base_dir.mkdir()
    (base_dir / "doc.md").write_text("# Doc", encoding="utf-8")

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    app = TenantApp(tenant)
    result = await app.browse_tree(path="", depth=1)

    assert result.nodes


@pytest.mark.unit
@pytest.mark.asyncio
async def test_browse_tree_handles_build_error(tmp_path: Path, monkeypatch):
    tenant = _make_filesystem_config(tmp_path)
    app = TenantApp(tenant)

    async def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(app, "_build_directory_tree", _raise)

    result = await app.browse_tree(path="", depth=1)

    assert result.error.startswith("Browse failed")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_directory_tree_zero_depth_returns_empty(tmp_path: Path):
    tenant = _make_filesystem_config(tmp_path)
    app = TenantApp(tenant)
    target = tmp_path

    nodes = await app._build_directory_tree(target, target, max_depth=0)

    assert nodes == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_directory_tree_skips_out_of_base(tmp_path: Path):
    tenant = _make_filesystem_config(tmp_path)
    app = TenantApp(tenant)
    base_dir = tmp_path / "base"
    target_dir = tmp_path / "target"
    base_dir.mkdir()
    target_dir.mkdir()
    (target_dir / "doc.md").write_text("# Doc", encoding="utf-8")

    nodes = await app._build_directory_tree(target_dir, base_dir, max_depth=1)

    assert nodes == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_directory_tree_permission_error(tmp_path: Path, monkeypatch):
    tenant = _make_filesystem_config(tmp_path)
    app = TenantApp(tenant)

    def _raise():
        raise PermissionError("nope")

    monkeypatch.setattr(Path, "iterdir", lambda _self: _raise())

    nodes = await app._build_directory_tree(tmp_path, tmp_path, max_depth=1)

    assert nodes == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_directory_tree_generic_error(tmp_path: Path, monkeypatch):
    tenant = _make_filesystem_config(tmp_path)
    app = TenantApp(tenant)

    def _raise():
        raise RuntimeError("boom")

    monkeypatch.setattr(Path, "iterdir", lambda _self: _raise())

    nodes = await app._build_directory_tree(tmp_path, tmp_path, max_depth=1)

    assert nodes == []


@pytest.mark.unit
def test_should_autostart_scheduler_git():
    config = TenantConfig(
        source_type="git",
        codename="git",
        docs_name="Git Docs",
        git_repo_url="https://example.com/repo.git",
        git_subpaths=["docs"],
        refresh_schedule="0 0 * * *",
    )

    assert _should_autostart_scheduler(config) is True


@pytest.mark.unit
def test_resolve_docs_root_handles_relative_paths(tmp_path: Path, monkeypatch):
    tenant = _make_filesystem_config(tmp_path)
    tenant.docs_root_dir = "relative-root"
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    resolved = _resolve_docs_root(tenant)

    assert resolved.is_absolute()


@pytest.mark.unit
def test_build_settings_includes_infra_fields(tmp_path: Path, monkeypatch):
    tenant = _make_filesystem_config(tmp_path)
    infra = SharedInfraConfig(
        http_timeout=15,
        max_concurrent_requests=5,
        operation_mode="online",
        article_extractor_fallback=ArticleExtractorFallbackConfig(enabled=True, endpoint="http://fallback"),
    )
    tenant._infrastructure = infra
    monkeypatch.setattr("docs_mcp_server.config.Settings._warm_fallback_endpoint", lambda *_args, **_kwargs: None)

    settings = _build_settings(tenant)

    assert settings.http_timeout == 15
    assert settings.max_concurrent_requests == 5
    assert settings.fallback_extractor_enabled is True


@pytest.mark.unit
def test_build_scheduler_service_git_missing_details(tmp_path: Path):
    config = TenantConfig.model_construct(
        source_type="git",
        codename="git",
        docs_name="Git Docs",
        git_repo_url=None,
        git_subpaths=None,
    )

    with pytest.raises(ValueError, match="missing repo details"):
        _build_scheduler_service(config)


@pytest.mark.unit
def test_build_scheduler_service_git_success(tmp_path: Path):
    config = TenantConfig(
        source_type="git",
        codename="git",
        docs_name="Git Docs",
        git_repo_url="https://example.com/repo.git",
        git_subpaths=["docs"],
        docs_root_dir=str(tmp_path / "docs"),
    )

    service = _build_scheduler_service(config)

    assert isinstance(service, GitSyncSchedulerService)


@pytest.mark.unit
def test_build_scheduler_service_returns_uow_factory(tmp_path: Path):
    config = _make_filesystem_config(tmp_path)
    service = _build_scheduler_service(config)

    uow = service.uow_factory()
    assert isinstance(uow, FileSystemUnitOfWork)
