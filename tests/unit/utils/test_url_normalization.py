"""Unit tests for URL normalization helpers."""

from docs_mcp_server.utils.url_normalization import canonicalize_markdown_mirror_url


def _allow_all(_url: str) -> bool:
    return True


def _reject_all(_url: str) -> bool:
    return False


def test_markdown_mirror_normalizer_rejects_empty_url() -> None:
    assert (
        canonicalize_markdown_mirror_url(
            "",
            enabled=True,
            markdown_url_suffix=".md",
            preserve_query_strings=True,
            should_process_url=_allow_all,
        )
        is None
    )


def test_disabled_normalizer_only_filters_url() -> None:
    assert (
        canonicalize_markdown_mirror_url(
            "https://example.com/docs/page",
            enabled=False,
            markdown_url_suffix=".md.txt",
            preserve_query_strings=True,
            should_process_url=_allow_all,
        )
        == "https://example.com/docs/page"
    )


def test_disabled_normalizer_applies_filter() -> None:
    assert (
        canonicalize_markdown_mirror_url(
            "https://example.com/docs/page",
            enabled=False,
            markdown_url_suffix=".md.txt",
            preserve_query_strings=True,
            should_process_url=_reject_all,
        )
        is None
    )


def test_markdown_mirror_normalizer_without_suffix_only_filters_url() -> None:
    assert (
        canonicalize_markdown_mirror_url(
            "https://example.com/docs/page",
            enabled=True,
            markdown_url_suffix=" ",
            preserve_query_strings=True,
            should_process_url=_allow_all,
        )
        == "https://example.com/docs/page"
    )


def test_markdown_mirror_normalizer_appends_suffix_and_drops_query() -> None:
    assert (
        canonicalize_markdown_mirror_url(
            "https://developer.android.com/ndk/guides/concepts?hl=en",
            enabled=True,
            markdown_url_suffix=".md.txt",
            preserve_query_strings=False,
            should_process_url=_allow_all,
        )
        == "https://developer.android.com/ndk/guides/concepts.md.txt"
    )


def test_markdown_mirror_normalizer_rejects_non_http_and_empty_paths() -> None:
    assert (
        canonicalize_markdown_mirror_url(
            "file:///tmp/page",
            enabled=True,
            markdown_url_suffix=".md",
            preserve_query_strings=True,
            should_process_url=_allow_all,
        )
        is None
    )
    assert (
        canonicalize_markdown_mirror_url(
            "https://example.com/",
            enabled=True,
            markdown_url_suffix=".md",
            preserve_query_strings=True,
            should_process_url=_allow_all,
        )
        is None
    )


def test_markdown_mirror_normalizer_strips_html_extension() -> None:
    assert (
        canonicalize_markdown_mirror_url(
            "https://example.com/docs/page.html",
            enabled=True,
            markdown_url_suffix=".md",
            preserve_query_strings=True,
            should_process_url=_allow_all,
        )
        == "https://example.com/docs/page.md"
    )


def test_markdown_mirror_normalizer_rejects_text_fragments() -> None:
    assert (
        canonicalize_markdown_mirror_url(
            "https://developer.android.com/ndk/guides/this%20also%20helps%0Akeep%20details",
            enabled=True,
            markdown_url_suffix=".md.txt",
            preserve_query_strings=False,
            should_process_url=_allow_all,
        )
        is None
    )


def test_markdown_mirror_normalizer_rejects_assets() -> None:
    assert (
        canonicalize_markdown_mirror_url(
            "https://example.com/docs/image.png",
            enabled=True,
            markdown_url_suffix=".md",
            preserve_query_strings=True,
            should_process_url=_allow_all,
        )
        is None
    )
