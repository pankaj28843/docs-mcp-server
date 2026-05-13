import importlib.util
from pathlib import Path
import sys


_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "apple_docc_snapshot.py"
_SPEC = importlib.util.spec_from_file_location("apple_docc_snapshot", _SCRIPT_PATH)
assert _SPEC is not None
apple_docc_snapshot = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = apple_docc_snapshot
_SPEC.loader.exec_module(apple_docc_snapshot)


def test_documentation_url_to_data_url_preserves_docc_path_segments():
    url = "https://developer.apple.com/documentation/SwiftUI/View/modifier(_:)"

    assert (
        apple_docc_snapshot.documentation_url_to_data_url(url)
        == f"{apple_docc_snapshot.APPLE_DOCC_DATA_BASE_URL}/SwiftUI/View/modifier(_:).json"
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
