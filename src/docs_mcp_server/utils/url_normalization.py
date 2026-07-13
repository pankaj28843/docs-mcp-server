"""URL normalization helpers for sync discovery."""

from collections.abc import Callable
from urllib.parse import unquote, urlsplit, urlunsplit


_STRIPPABLE_DOCUMENT_EXTENSIONS = {"html", "htm", "ipynb"}
_TEXT_LINK_MARKERS = ("\n", "\r", "\t", " ", "`", "<", ">")


def canonicalize_markdown_mirror_url(
    url: str,
    *,
    enabled: bool,
    markdown_url_suffix: str | None,
    preserve_query_strings: bool,
    should_process_url: Callable[[str], bool],
) -> str | None:
    """Return the fetch URL that should be enqueued for a discovered URL.

    When disabled, this is only a filtering wrapper. When enabled, document-like
    URLs are rewritten to a raw Markdown mirror by appending the configured
    suffix. Malformed text-as-link URLs are rejected before they pollute the
    retry queue.
    """
    if not url:
        return None

    if not enabled:
        return url if should_process_url(url) else None

    suffix = (markdown_url_suffix or "").strip()
    if not suffix:
        return url if should_process_url(url) else None

    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    path = (parsed.path or "").rstrip("/")
    if not path:
        return None

    decoded_path = unquote(path)
    if any(marker in decoded_path for marker in _TEXT_LINK_MARKERS):
        return None

    if path.endswith(suffix):
        markdown_path = path
    else:
        last_segment = path.rsplit("/", 1)[-1]
        if "." in last_segment:
            _base, extension = last_segment.rsplit(".", 1)
            if extension.lower() not in _STRIPPABLE_DOCUMENT_EXTENSIONS:
                return None
            path = path[: -(len(extension) + 1)]
        markdown_path = f"{path}{suffix}"

    query = parsed.query if preserve_query_strings else ""
    canonical_url = urlunsplit((parsed.scheme, parsed.netloc, markdown_path, query, ""))
    return canonical_url if should_process_url(canonical_url) else None
