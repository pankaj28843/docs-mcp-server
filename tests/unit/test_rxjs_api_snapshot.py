"""Behavior checks for the official RxJS API snapshot converter."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import shutil

import pytest

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.search.indexer import TenantIndexer, TenantIndexingContext
from docs_mcp_server.tenant import TenantApp
from docs_mcp_server.utils.front_matter import parse_front_matter


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "rxjs_api_snapshot.py"
SPEC = spec_from_file_location("rxjs_api_snapshot", SCRIPT)
assert SPEC and SPEC.loader
snapshot = module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)


@pytest.mark.unit
def test_api_paths_include_module_and_all_public_items() -> None:
    manifest = [
        {"title": "index", "items": [{"path": "api/index/class/Observable"}, {"path": "api/index/function/of"}]}
    ]
    assert snapshot.api_paths(manifest) == (
        "api/index",
        "api/index/class/Observable",
        "api/index/function/of",
    )


@pytest.mark.unit
def test_api_paths_reject_duplicate_and_unsafe_items() -> None:
    for items in (
        [{"path": "api/index/class/Observable"}, {"path": "api/index/class/Observable"}],
        [{"path": "api/../../secrets"}],
    ):
        with pytest.raises(ValueError, match="RxJS API path"):
            snapshot.api_paths([{"title": "index", "items": items}])


@pytest.mark.unit
def test_render_page_preserves_content_and_source_provenance() -> None:
    contents = (
        '<article><a href="https://github.com/reactivex/rxjs/tree/7.8.2/src/Observable.ts">View Source</a>'
        "<h1>Observable</h1><p>Subscribe to a stream of values.</p>"
        "<pre><code>source.subscribe(next)</code></pre></article>"
    )
    markdown = snapshot.render_page(
        "api/index/class/Observable",
        {"id": "api/index/class/Observable", "title": "Observable", "contents": contents},
        "7.8.2",
        "2026-11-02T00:00:00+00:00",
    )
    assert "url: https://rxjs.dev/api/index/class/Observable" in markdown
    assert "source_version: 7.8.2" in markdown
    assert "source.subscribe(next)" in markdown
    assert "Subscribe to a stream of values." in markdown
    metadata, body = parse_front_matter(markdown)
    assert metadata["url"] == "https://rxjs.dev/api/index/class/Observable"
    assert body.startswith("# Observable")


@pytest.mark.unit
def test_render_page_rejects_version_drift() -> None:
    page = {
        "id": "api/index",
        "title": "index",
        "contents": '<a href="https://github.com/reactivex/rxjs/tree/8.0.0/src/index.ts">source</a><p>Rich module contents here.</p>',
    }
    with pytest.raises(ValueError, match="version mismatch"):
        snapshot.render_page("api/index", page, "7.8.2", "2026-11-02T00:00:00+00:00")


@pytest.mark.unit
def test_failed_atomic_promotion_preserves_previous_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "rxjs-api" / "api-snapshot"
    output.mkdir(parents=True)
    (output / "old.md").write_text("old content", encoding="utf-8")
    staging = snapshot._create_staging_directory(output)
    (staging / "new.md").write_text("new content", encoding="utf-8")

    def fail_exchange(_staging: Path, _output: Path) -> None:
        raise OSError("renameat2 failed")

    monkeypatch.setattr(snapshot, "_exchange_directories", fail_exchange)
    with pytest.raises(OSError, match="renameat2 failed"):
        snapshot._publish_snapshot(staging, output)

    assert (output / "old.md").read_text(encoding="utf-8") == "old content"
    assert not (output / "new.md").exists()
    assert not staging.exists()


@pytest.mark.unit
def test_atomic_promotion_replaces_snapshot_without_leaking_old_pages(tmp_path: Path) -> None:
    output = tmp_path / "rxjs-api" / "api-snapshot"
    output.mkdir(parents=True)
    (output / "old.md").write_text("old content", encoding="utf-8")
    staging = snapshot._create_staging_directory(output)
    (staging / "new.md").write_text("new content", encoding="utf-8")

    snapshot._publish_snapshot(staging, output)

    assert (output / "new.md").read_text(encoding="utf-8") == "new content"
    assert not (output / "old.md").exists()
    assert not staging.exists()


@pytest.mark.unit
def test_macos_atomic_promotion_uses_rename_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "rxjs-api" / "api-snapshot"
    staging = output.parent / ".staging_api-snapshot-test"
    calls: list[tuple[object, ...]] = []

    def renamex_np(*args: object) -> int:
        calls.append(args)
        return 0

    class LibC:
        pass

    libc = LibC()
    libc.renamex_np = renamex_np
    monkeypatch.setattr(snapshot.sys, "platform", "darwin")
    monkeypatch.setattr(snapshot.ctypes, "CDLL", lambda *_args, **_kwargs: libc)

    snapshot._exchange_directories(staging, output)

    assert calls == [(snapshot.os.fsencode(staging), snapshot.os.fsencode(output), 2)]


@pytest.mark.unit
def test_atomic_promotion_rejects_unsupported_platform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(snapshot.sys, "platform", "win32")
    with pytest.raises(RuntimeError, match="unsupported on win32"):
        snapshot._exchange_directories(tmp_path / "stage", tmp_path / "output")


@pytest.mark.unit
def test_staged_pages_are_outside_indexable_tenant_root(tmp_path: Path) -> None:
    docs_root = tmp_path / "rxjs-api"
    output = docs_root / "api-snapshot"
    output.mkdir(parents=True)
    (output / "old.md").write_text("-----\nurl: https://rxjs.dev/api/old\n-----\n# Old\n", encoding="utf-8")
    staging = snapshot._create_staging_directory(output)
    try:
        assert staging.is_relative_to(docs_root)
        assert staging.name.startswith(".staging_")
        (staging / "new.md").write_text("-----\nurl: https://rxjs.dev/api/new\n-----\n# New\n", encoding="utf-8")
        result = TenantIndexer(
            TenantIndexingContext(
                codename="rxjs-api",
                docs_root=docs_root,
                segments_dir=docs_root / "__search_segments",
                source_type="filesystem",
            )
        ).build_segment()
        assert result.documents_indexed == 1
        assert result.errors == ()
    finally:
        shutil.rmtree(staging)


@pytest.mark.unit
def test_staged_pages_do_not_count_as_live_tenant_docs(tmp_path: Path) -> None:
    docs_root = tmp_path / "rxjs-api"
    staging = snapshot._create_staging_directory(docs_root / "api-snapshot")
    (staging / "new.md").write_text("# New API page\n", encoding="utf-8")
    tenant = TenantApp(
        TenantConfig(source_type="filesystem", codename="rxjs-api", docs_name="RxJS API", docs_root_dir=str(docs_root))
    )

    assert not tenant._has_docs()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nested_snapshot_fetch_returns_full_markdown(tmp_path: Path) -> None:
    docs_root = tmp_path / "rxjs-api"
    page = docs_root / "api-snapshot" / "api" / "index" / "class" / "Observable.md"
    page.parent.mkdir(parents=True)
    url = "https://rxjs.dev/api/index/class/Observable"
    page.write_text(f"-----\nurl: {url}\n-----\n# Observable\n" + "subscribe to values.\n" * 300, encoding="utf-8")
    result = TenantIndexer(
        TenantIndexingContext(
            codename="rxjs-api",
            docs_root=docs_root,
            segments_dir=docs_root / "__search_segments",
            source_type="filesystem",
        )
    ).build_segment()
    assert result.documents_indexed == 1
    tenant = TenantApp(
        TenantConfig(source_type="filesystem", codename="rxjs-api", docs_name="RxJS API", docs_root_dir=str(docs_root))
    )

    response = await tenant.fetch(url)

    assert response.error is None
    assert response.title == "Observable"
    assert response.content == page.read_text(encoding="utf-8")
    assert len(response.content) > 4096
