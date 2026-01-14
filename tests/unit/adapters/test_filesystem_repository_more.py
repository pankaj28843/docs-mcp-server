"""Additional tests for filesystem repository edge cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docs_mcp_server.adapters.filesystem_repository import META_FILE_EXTENSION, FileSystemRepository
from docs_mcp_server.domain.model import Document
from docs_mcp_server.utils.path_builder import PathBuilder
from docs_mcp_server.utils.url_translator import UrlTranslator


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_returns_none_when_markdown_read_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FileSystemRepository(base_dir=tmp_path, url_translator=UrlTranslator(tmp_path))
    url = "https://example.com/doc"
    content_path = repo.url_translator.get_internal_path_from_public_url(url)
    content_path.write_text("# Doc", encoding="utf-8")
    content_path.with_suffix(META_FILE_EXTENSION).write_text("{}", encoding="utf-8")

    async def _read_fail(_path: Path):
        return None

    monkeypatch.setattr(repo, "_read_markdown_with_front_matter", _read_fail)

    assert await repo.get(url) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_skips_invalid_metadata(tmp_path: Path) -> None:
    repo = FileSystemRepository(base_dir=tmp_path, url_translator=UrlTranslator(tmp_path))
    (tmp_path / "bad.meta.json").write_text("{bad json", encoding="utf-8")
    (tmp_path / "missing.meta.json").write_text(json.dumps({"url": "", "title": ""}), encoding="utf-8")
    (tmp_path / "invalid.meta.json").write_text(json.dumps({"url": "not-a-url", "title": "Invalid"}), encoding="utf-8")
    (tmp_path / "valid.meta.json").write_text(
        json.dumps({"url": "https://example.com/ok", "title": "OK"}), encoding="utf-8"
    )

    documents = await repo.list()

    assert len(documents) == 1
    assert isinstance(documents[0], Document)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_returns_false_when_missing(tmp_path: Path) -> None:
    repo = FileSystemRepository(base_dir=tmp_path, url_translator=UrlTranslator(tmp_path))

    assert await repo.delete("https://example.com/missing") is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_handles_unlink_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FileSystemRepository(base_dir=tmp_path, url_translator=UrlTranslator(tmp_path))
    url = "https://example.com/delete-me"
    content_path = repo.url_translator.get_internal_path_from_public_url(url)
    content_path.write_text("content", encoding="utf-8")
    meta_path = content_path.with_suffix(META_FILE_EXTENSION)
    meta_path.write_text("{}", encoding="utf-8")

    original_unlink = Path.unlink

    def _unlink(path: Path, *args, **kwargs):
        if path == content_path:
            raise OSError("unlink boom")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _unlink)

    assert await repo.delete(url) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_by_path_builder_handles_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path_builder = PathBuilder()
    repo = FileSystemRepository(base_dir=tmp_path, url_translator=UrlTranslator(tmp_path), path_builder=path_builder)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(path_builder, "build_markdown_path", _boom)

    assert await repo.delete_by_path_builder("https://example.com/doc") is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_by_url_translator_handles_unlink_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FileSystemRepository(base_dir=tmp_path, url_translator=UrlTranslator(tmp_path))
    url = "https://example.com/delete"
    content_path = repo.url_translator.get_internal_path_from_public_url(url)
    content_path.write_text("content", encoding="utf-8")
    meta_path = content_path.with_suffix(META_FILE_EXTENSION)
    meta_path.write_text("{}", encoding="utf-8")

    original_unlink = Path.unlink

    def _unlink(path: Path, *args, **kwargs):
        if path == content_path:
            raise OSError("unlink boom")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _unlink)

    assert await repo.delete_by_url_translator(url) is False


@pytest.mark.unit
def test_prune_empty_dirs_handles_outside_and_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FileSystemRepository(base_dir=tmp_path, url_translator=UrlTranslator(tmp_path))

    external_dir = tmp_path / "external"
    external_dir.mkdir()
    (external_dir / "file.txt").write_text("x", encoding="utf-8")

    repo._prune_empty_dirs(external_dir)  # pylint: disable=protected-access

    def _resolve(_self):
        raise RuntimeError("resolve boom")

    monkeypatch.setattr(Path, "resolve", _resolve)

    repo._prune_empty_dirs(tmp_path / "missing")  # pylint: disable=protected-access
