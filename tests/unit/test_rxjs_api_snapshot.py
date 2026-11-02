"""Behavior checks for the official RxJS API snapshot converter."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

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
