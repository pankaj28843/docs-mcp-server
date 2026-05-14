import importlib.util
import json
from pathlib import Path
import sys


_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "apple_rendered_link_bfs.py"
_SPEC = importlib.util.spec_from_file_location("apple_rendered_link_bfs", _SCRIPT_PATH)
assert _SPEC is not None
apple_rendered_link_bfs = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = apple_rendered_link_bfs
_SPEC.loader.exec_module(apple_rendered_link_bfs)


class FakeBrowser:
    def __init__(self, graph):
        self.graph = graph
        self.opened = []
        self.preflight_calls = 0

    def preflight(self):
        self.preflight_calls += 1

    def extract_links(self, url):
        self.opened.append(url)
        return tuple(self.graph.get(url, ()))


def test_normalize_documentation_url_whitelists_apple_documentation_prefix():
    assert (
        apple_rendered_link_bfs.normalize_documentation_url(
            "https://developer.apple.com/documentation/xcode?changes=latest#overview"
        )
        == "https://developer.apple.com/documentation/xcode"
    )
    assert (
        apple_rendered_link_bfs.normalize_documentation_url("https://developer.apple.com/documentation")
        == apple_rendered_link_bfs.DOCUMENTATION_PREFIX
    )
    assert apple_rendered_link_bfs.normalize_documentation_url("http://developer.apple.com/documentation/xcode") is None
    assert apple_rendered_link_bfs.normalize_documentation_url("https://developer.apple.com/news/") is None


def test_normalize_documentation_url_strips_leading_bom_from_absolute_url():
    assert (
        apple_rendered_link_bfs.normalize_documentation_url(
            "\ufeffhttps://developer.apple.com/documentation/storekit/storeview"
        )
        == "https://developer.apple.com/documentation/storekit/storeview"
    )
    assert (
        apple_rendered_link_bfs.normalize_documentation_url(
            "%25EF%25BB%25BFhttps://developer.apple.com/documentation/storekit/transaction"
        )
        == "https://developer.apple.com/documentation/storekit/transaction"
    )


def test_normalize_documentation_url_rejects_embedded_bom_absolute_url_loops():
    assert (
        apple_rendered_link_bfs.normalize_documentation_url(
            "https://developer.apple.com/documentation/ios-ipados-release-notes/"
            "%252525EF%252525BB%252525BFhttps:/developer.apple.com/documentation/storekit/storeview"
        )
        is None
    )
    assert (
        apple_rendered_link_bfs.normalize_documentation_url(
            "https://developer.apple.com/documentation/xcode-release-notes/"
            "%EF%BB%BFhttps:/developer.apple.com/help/app-store-connect/manage-subscriptions/set-up-offer-codes"
        )
        is None
    )


def test_extract_root_groups_from_docc_payload_reads_identifiers_and_reference_urls():
    payload = {
        "identifier": "doc://com.apple.documentation/documentation/Xcode/creating-an-xcode-project-for-an-app",
        "references": {
            "swiftui": {"url": "/documentation/swiftui/view"},
            "private": {"url": "/documentation/_secret/page"},
        },
    }

    assert apple_rendered_link_bfs.extract_root_groups_from_docc_payload(payload) == {"Xcode", "swiftui"}


def test_links_from_eval_payload_accepts_json_string_and_normalizes_links():
    payload = {
        "result": {
            "value": json.dumps(
                [
                    "https://developer.apple.com/documentation/xcode?changes=latest#overview",
                    "https://developer.apple.com/news/",
                    "https://developer.apple.com/documentation/",
                ]
            )
        }
    }

    assert apple_rendered_link_bfs._links_from_eval_payload(payload) == (
        "https://developer.apple.com/documentation/xcode",
        "https://developer.apple.com/documentation/",
    )


def test_crawl_rendered_documentation_links_drops_malformed_embedded_url_loops(tmp_path):
    root = apple_rendered_link_bfs.DOCUMENTATION_PREFIX
    xcode = "https://developer.apple.com/documentation/xcode"
    malformed = (
        "https://developer.apple.com/documentation/ios-ipados-release-notes/"
        "%252525EF%252525BB%252525BFhttps:/developer.apple.com/documentation/storekit/storeview"
    )
    browser = FakeBrowser({root: [xcode, malformed], xcode: []})
    options = apple_rendered_link_bfs.RenderedLinkBfsOptions(
        urls_file=tmp_path / "urls.json",
        state_file=tmp_path / "state.json",
    )

    result = apple_rendered_link_bfs.crawl_rendered_documentation_links(options, browser=browser)

    assert browser.opened == [root, xcode]
    assert result.discovered_urls == 1
    assert json.loads(options.urls_file.read_text(encoding="utf-8")) == [xcode]


def test_crawl_rendered_documentation_links_filters_to_on_demand_scope_terms(tmp_path):
    root = apple_rendered_link_bfs.DOCUMENTATION_PREFIX
    xcode = "https://developer.apple.com/documentation/xcode"
    swiftui = "https://developer.apple.com/documentation/swiftui"
    ios = "https://developer.apple.com/documentation/ios-ipados-release-notes"
    xcode_child = "https://developer.apple.com/documentation/xcode/build-system"
    swiftui_child = "https://developer.apple.com/documentation/swiftui/view"
    browser = FakeBrowser(
        {
            root: [xcode, swiftui, ios],
            xcode: [xcode_child],
            ios: [],
            swiftui: [swiftui_child],
            xcode_child: [],
            swiftui_child: [],
        }
    )
    options = apple_rendered_link_bfs.RenderedLinkBfsOptions(
        urls_file=tmp_path / "urls.json",
        state_file=tmp_path / "state.json",
        scope_terms=("xcode", "ios", "ipados"),
    )

    result = apple_rendered_link_bfs.crawl_rendered_documentation_links(options, browser=browser)

    assert browser.opened == [root, xcode, ios, xcode_child]
    assert result.discovered_urls == 3
    assert set(json.loads(options.urls_file.read_text(encoding="utf-8"))) == {xcode, ios, xcode_child}


def test_crawl_rendered_documentation_links_visits_root_groups_before_deeper_pages(tmp_path):
    root = apple_rendered_link_bfs.DOCUMENTATION_PREFIX
    xcode = "https://developer.apple.com/documentation/xcode"
    swiftui = "https://developer.apple.com/documentation/swiftui"
    xcode_child = "https://developer.apple.com/documentation/xcode/writing-code-with-intelligence-in-xcode"
    swiftui_child = "https://developer.apple.com/documentation/swiftui/view"
    browser = FakeBrowser(
        {
            root: [xcode, swiftui, "https://developer.apple.com/news/"],
            xcode: [xcode_child, root],
            swiftui: [swiftui_child],
            xcode_child: [],
            swiftui_child: [],
        }
    )
    options = apple_rendered_link_bfs.RenderedLinkBfsOptions(
        urls_file=tmp_path / "urls.json",
        state_file=tmp_path / "state.json",
        checkpoint_every=1,
    )

    result = apple_rendered_link_bfs.crawl_rendered_documentation_links(options, browser=browser)

    assert browser.preflight_calls == 1
    assert browser.opened == [root, xcode, swiftui, xcode_child, swiftui_child]
    assert result.discovered_urls == 4
    assert result.visited_pages == 5
    assert set(json.loads(options.urls_file.read_text(encoding="utf-8"))) == {
        xcode,
        swiftui,
        xcode_child,
        swiftui_child,
    }
    state = json.loads(options.state_file.read_text(encoding="utf-8"))
    assert state["queue"] == []
    assert root in state["visited"]
