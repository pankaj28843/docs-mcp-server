"""Additional unit tests for filesystem unit of work helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from docs_mcp_server.service_layer.filesystem_unit_of_work import (
    AbstractUnitOfWork,
    FileSystemUnitOfWork,
    cleanup_orphaned_staging_dirs,
)
from docs_mcp_server.utils.path_builder import PathBuilder
from docs_mcp_server.utils.url_translator import UrlTranslator


class _DummyUow(AbstractUnitOfWork):
    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_abstract_uow_enter_returns_self():
    uow = _DummyUow()
    assert await uow.__aenter__() is uow


@pytest.mark.unit
def test_cleanup_orphaned_staging_dirs_skips_files(tmp_path: Path):
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    assert cleanup_orphaned_staging_dirs(tmp_path, max_age_hours=0) == 0


@pytest.mark.unit
def test_cleanup_orphaned_staging_dirs_handles_rmtree_error(tmp_path: Path, monkeypatch):
    staging = tmp_path / ".staging_test"
    staging.mkdir()

    monkeypatch.setattr(
        "docs_mcp_server.service_layer.filesystem_unit_of_work.shutil.rmtree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("boom")),
    )

    assert cleanup_orphaned_staging_dirs(tmp_path, max_age_hours=0) == 0


@pytest.mark.unit
def test_cleanup_orphaned_staging_dirs_handles_iter_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "iterdir", lambda _self: (_ for _ in ()).throw(OSError("boom")))

    assert cleanup_orphaned_staging_dirs(tmp_path, max_age_hours=0) == 0


@pytest.mark.unit
def test_merge_staging_into_base_no_staging(tmp_path: Path):
    uow = FileSystemUnitOfWork(
        base_dir=tmp_path,
        url_translator=UrlTranslator(tmp_path),
        path_builder=PathBuilder(),
    )
    if uow.staging_dir.exists():
        uow.staging_dir.rmdir()

    uow._merge_staging_into_base()


@pytest.mark.unit
def test_merge_staging_into_base_replaces_directory(tmp_path: Path):
    uow = FileSystemUnitOfWork(
        base_dir=tmp_path,
        url_translator=UrlTranslator(tmp_path),
        path_builder=PathBuilder(),
    )
    uow.staging_dir.mkdir(parents=True, exist_ok=True)

    staged_path = uow.staging_dir / "doc"
    staged_path.write_text("content", encoding="utf-8")

    dest_dir = tmp_path / "doc"
    dest_dir.mkdir()

    uow._merge_staging_into_base()

    assert (tmp_path / "doc").is_file()
