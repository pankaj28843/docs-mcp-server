"""Boundary-safe matching for configured documentation URL prefixes."""

from urllib.parse import urlsplit


def url_matches_prefix(url: str, prefix: str) -> bool:
    """Return whether *url* belongs to the path rooted at *prefix*.

    Prefix configuration is intentionally URL-oriented rather than a raw string
    filter. A rule for ``/design`` therefore matches ``/design`` and
    ``/design/...`` (including the crawler's ``.md.txt`` mirror), but not a
    sibling such as ``/design-for-safety``. Query strings do not affect the
    decision because crawl settings normally canonicalize them away.
    """

    candidate = (url or "").strip()
    rule = (prefix or "").strip()
    if not candidate or not rule:
        return False

    parsed_url = urlsplit(candidate)
    parsed_rule = urlsplit(rule)
    if not parsed_url.scheme or not parsed_url.netloc or not parsed_rule.scheme or not parsed_rule.netloc:
        # Preserve useful behavior for test fixtures and non-URL legacy values
        # while applying strict URL matching to production rules.
        return candidate.startswith(rule)

    if parsed_url.scheme.lower() != parsed_rule.scheme.lower():
        return False
    if parsed_url.netloc.lower() != parsed_rule.netloc.lower():
        return False

    rule_path = parsed_rule.path or "/"
    candidate_path = parsed_url.path or "/"
    if rule_path == "/":
        return True

    root = rule_path.rstrip("/") or "/"
    normalized_candidate = candidate_path.rstrip("/") or "/"
    return normalized_candidate == root or normalized_candidate.startswith((f"{root}/", f"{root}."))
