from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys

import pytest


_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "apple_docc_snapshot.py"
_SPEC = importlib.util.spec_from_file_location("apple_docc_snapshot", _SCRIPT_PATH)
assert _SPEC is not None
apple_docc_snapshot = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = apple_docc_snapshot
_SPEC.loader.exec_module(apple_docc_snapshot)


class FakeDocCResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status = 200
        self.headers = {"content-type": "application/json"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self.payload


class FakeDocCSession:
    def __init__(self, payload):
        self.payload = payload
        self.requested_url = None

    def get(self, url):
        self.requested_url = url
        return FakeDocCResponse(self.payload)


def test_documentation_url_to_data_url_preserves_docc_path_segments():
    url = "https://developer.apple.com/documentation/SwiftUI/View/modifier(_:)"

    assert (
        apple_docc_snapshot.documentation_url_to_data_url(url)
        == f"{apple_docc_snapshot.APPLE_DOCC_DATA_BASE_URL}/SwiftUI/View/modifier(_:).json"
    )


def test_documentation_url_to_path_rejects_embedded_bom_absolute_url_loops():
    assert (
        apple_docc_snapshot.documentation_url_to_path(
            "https://developer.apple.com/documentation/ios-ipados-release-notes/"
            "%252525EF%252525BB%252525BFhttps:/developer.apple.com/documentation/storekit/storeview"
        )
        is None
    )
    assert (
        apple_docc_snapshot.documentation_url_to_path(
            "\ufeffhttps://developer.apple.com/documentation/storekit/storeview"
        )
        == "storekit/storeview"
    )


def test_extract_documentation_paths_from_identifiers_and_reference_urls():
    payload = {
        "identifier": "doc://com.apple.SwiftUI/documentation/SwiftUI/View",
        "references": {
            "topic": {
                "url": "/documentation/foundationmodels/generationoptions",
            },
            "external": "https://example.com/not-documentation",
        },
        "topicSections": [
            {
                "identifiers": [
                    "doc://com.apple.documentation/documentation/Xcode/writing-code-with-intelligence-in-xcode"
                ]
            }
        ],
    }

    assert apple_docc_snapshot.extract_documentation_paths(payload) == {
        "SwiftUI/View",
        "foundationmodels/generationoptions",
        "Xcode/writing-code-with-intelligence-in-xcode",
    }


def test_select_documentation_urls_deduplicates_lowercase_variants_and_prefers_canonical_case():
    urls = [
        "https://developer.apple.com/documentation/swiftui/view",
        "https://developer.apple.com/documentation/SwiftUI/View",
        "https://developer.apple.com/documentation/accessibility",
    ]

    selected = apple_docc_snapshot.select_documentation_urls(urls, required_urls=(), max_docs=10)

    assert selected == (
        "https://developer.apple.com/documentation/accessibility",
        "https://developer.apple.com/documentation/SwiftUI/View",
    )


def test_select_documentation_urls_treats_zero_max_docs_as_no_cap():
    urls = [
        "https://developer.apple.com/documentation/xcode",
        "https://developer.apple.com/documentation/swiftui",
    ]

    assert apple_docc_snapshot.select_documentation_urls(urls, required_urls=(), max_docs=0) == (
        "https://developer.apple.com/documentation/swiftui",
        "https://developer.apple.com/documentation/xcode",
    )


def test_merge_documentation_url_sequences_filters_non_documentation_urls():
    merged = apple_docc_snapshot._merge_documentation_url_sequences(
        [
            "https://developer.apple.com/documentation/xcode",
            "https://developer.apple.com/news/",
        ],
        ["https://developer.apple.com/documentation/swiftui"],
    )

    assert merged == (
        "https://developer.apple.com/documentation/xcode",
        "https://developer.apple.com/documentation/swiftui",
    )


def test_filter_documentation_urls_keeps_on_demand_scope_only():
    urls = (
        "https://developer.apple.com/documentation/xcode",
        "https://developer.apple.com/documentation/xcode/build-system",
        "https://developer.apple.com/documentation/ios-ipados-release-notes",
        "https://developer.apple.com/documentation/swiftui",
    )

    assert apple_docc_snapshot.filter_documentation_urls(urls, ("xcode", "ipad")) == (
        "https://developer.apple.com/documentation/xcode",
        "https://developer.apple.com/documentation/xcode/build-system",
        "https://developer.apple.com/documentation/ios-ipados-release-notes",
    )


async def test_queue_discovered_paths_prunes_out_of_scope_on_demand_discovery():
    queue = apple_docc_snapshot.asyncio.Queue()
    state = apple_docc_snapshot._DiscoveryState(
        include_url_patterns=apple_docc_snapshot._compile_include_url_patterns(("xcode",))
    )
    payload = {
        "references": {
            "xcode": {"url": "/documentation/xcode/build-system"},
            "swiftui": {"url": "/documentation/swiftui/view"},
        }
    }

    await apple_docc_snapshot._queue_discovered_paths(queue, state, payload, discovery_limit=0)

    queued = [await queue.get() for _ in range(queue.qsize())]
    assert queued == [
        (
            f"{apple_docc_snapshot.APPLE_DOCC_DATA_BASE_URL}/xcode/build-system.json",
            "xcode/build-system",
        )
    ]


def test_validate_options_refuses_clean_scoped_on_demand_sync(tmp_path):
    options = apple_docc_snapshot.AppleDocCSnapshotOptions(
        docs_root=tmp_path,
        clean=True,
        include_url_regexes=("xcode",),
    )

    with pytest.raises(apple_docc_snapshot.AppleDocCSnapshotError, match="Refusing --clean with scoped"):
        apple_docc_snapshot.validate_snapshot_options(options)


async def test_render_snapshot_documents_reuses_recent_existing_docs(tmp_path, monkeypatch):
    url = "https://developer.apple.com/documentation/xcode"
    snapshot_dir = tmp_path / "apple-docs"
    snapshot_dir.mkdir()
    path = apple_docc_snapshot._output_path_for_url(snapshot_dir, url)
    path.parent.mkdir(parents=True)
    fetched_at = datetime.now(UTC) - timedelta(hours=2)
    path.write_text(
        "-----\n"
        f"last_fetched_at: '{fetched_at.isoformat()}'\n"
        "source: Apple DocC JSON\n"
        "title: Xcode\n"
        f"url: {url}\n"
        "-----\n"
        "# Xcode\n\nCached body\n",
        encoding="utf-8",
    )

    async def fail_fetch(session, requested_url):
        raise AssertionError(f"unexpected fetch for {requested_url}")

    monkeypatch.setattr(apple_docc_snapshot, "fetch_and_render_document", fail_fetch)
    options = apple_docc_snapshot.AppleDocCSnapshotOptions(
        docs_root=tmp_path,
        refresh_max_age_hours=72,
    )

    assert await apple_docc_snapshot.render_snapshot_documents(options, [url]) == (0, 0, 1)
    assert path.read_text(encoding="utf-8").endswith("# Xcode\n\nCached body\n")


async def test_fetch_and_render_document_keeps_short_existing_docc_pages():
    session = FakeDocCSession({"metadata": {"title": "Tiny Doc", "role": "Article"}})

    document = await apple_docc_snapshot.fetch_and_render_document(
        session,
        "https://developer.apple.com/documentation/tiny",
    )

    assert document is not None
    assert session.requested_url == f"{apple_docc_snapshot.APPLE_DOCC_DATA_BASE_URL}/tiny.json"
    assert "# Tiny Doc" in document.markdown


def test_render_docc_json_includes_abstract_content_topics_and_reference_index():
    payload = {
        "kind": "article",
        "metadata": {
            "title": "View fundamentals",
            "roleHeading": "API Collection",
            "modules": [{"name": "SwiftUI"}],
        },
        "abstract": [{"type": "text", "text": "Define the visual elements of your app."}],
        "primaryContentSections": [
            {
                "kind": "content",
                "content": [
                    {"type": "heading", "level": 2, "text": "Overview"},
                    {
                        "type": "paragraph",
                        "inlineContent": [
                            {"type": "text", "text": "Views are building blocks."},
                            {
                                "type": "reference",
                                "identifier": "doc://com.apple.SwiftUI/documentation/SwiftUI/View",
                            },
                        ],
                    },
                ],
            }
        ],
        "topicSections": [
            {
                "title": "Creating a view",
                "identifiers": ["doc://com.apple.SwiftUI/documentation/SwiftUI/View"],
            }
        ],
        "references": {
            "doc://com.apple.SwiftUI/documentation/SwiftUI/View": {
                "title": "View",
                "url": "/documentation/swiftui/view",
                "abstract": [{"type": "text", "text": "A part of your app interface."}],
                "fragments": [
                    {"kind": "keyword", "text": "protocol"},
                    {"kind": "text", "text": " "},
                    {"kind": "identifier", "text": "View"},
                ],
            }
        },
    }

    rendered = apple_docc_snapshot.render_docc_json(
        payload,
        "https://developer.apple.com/documentation/SwiftUI/View-fundamentals",
    )

    assert rendered.title == "View fundamentals"
    assert "# View fundamentals" in rendered.markdown
    assert "API Collection; Modules: SwiftUI" in rendered.markdown
    assert "## Overview" in rendered.markdown
    assert (
        "Views are building blocks.[View](https://developer.apple.com/documentation/swiftui/view)" in rendered.markdown
    )
    assert "## Topics" in rendered.markdown
    assert "- [View](https://developer.apple.com/documentation/swiftui/view)" in rendered.markdown
    assert "## Referenced symbols and articles" in rendered.markdown
