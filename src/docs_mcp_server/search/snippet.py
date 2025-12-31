"""Snippet extraction with sentence-boundary awareness.

This module provides smart snippet extraction that respects sentence
boundaries for more readable search result previews.

Smart Defaults (no per-tenant config needed):
- Tries to start/end on sentence boundaries
- Falls back to word boundaries if no sentence found
- Highlights matching terms with configurable style
"""

from __future__ import annotations

from collections.abc import Sequence
import re


# Sentence-ending punctuation pattern
SENTENCE_END_PATTERN = re.compile(r"[.!?]\s+")
# Word boundary pattern (for fallback)
WORD_BOUNDARY_PATTERN = re.compile(r"\s+")


def find_sentence_start(text: str, position: int, max_lookback: int = 200) -> int:
    """Find the start of the sentence containing the position.

    Args:
        text: The full text to search in.
        position: The position to find sentence start for.
        max_lookback: Maximum characters to look back.

    Returns:
        Index of sentence start, or position - max_lookback if not found.
    """
    if position == 0:
        return 0

    # Look back from position to find sentence end (which is our start)
    start_search = max(0, position - max_lookback)
    search_text = text[start_search:position]

    # Find last sentence-ending punctuation before our position
    matches = list(SENTENCE_END_PATTERN.finditer(search_text))
    if matches:
        # Return position after the last sentence end
        last_match = matches[-1]
        return start_search + last_match.end()

    # No sentence boundary found, try to find a word boundary
    words = list(WORD_BOUNDARY_PATTERN.finditer(search_text))
    if words:
        # Return position after the last word boundary in first quarter
        quarter_pos = len(search_text) // 4
        for match in words:
            if match.start() >= quarter_pos:
                return start_search + match.end()

    # Fall back to max lookback position
    return start_search


def find_sentence_end(text: str, position: int, max_lookahead: int = 200) -> int:
    """Find the end of the sentence containing the position.

    Args:
        text: The full text to search in.
        position: The position to find sentence end for.
        max_lookahead: Maximum characters to look ahead.

    Returns:
        Index of sentence end, or position + max_lookahead if not found.
    """
    if position >= len(text):
        return len(text)

    # Look ahead from position to find sentence end
    end_search = min(len(text), position + max_lookahead)
    search_text = text[position:end_search]

    # Find first sentence-ending punctuation after our position
    match = SENTENCE_END_PATTERN.search(search_text)
    if match:
        # Include the punctuation and following space
        return position + match.end()

    # No sentence boundary found, try to find a word boundary
    words = list(WORD_BOUNDARY_PATTERN.finditer(search_text))
    if words:
        # Return position of last word boundary in last quarter
        three_quarter_pos = (len(search_text) * 3) // 4
        for match in reversed(words):
            if match.start() <= three_quarter_pos:
                return position + match.start()

    # Fall back to max lookahead position
    return end_search


def extract_sentence_snippet(
    text: str,
    match_position: int,
    match_length: int,
    max_chars: int = 300,
    surrounding_context: int = 100,
) -> tuple[str, int, int]:
    """Extract a snippet that respects sentence boundaries.

    Args:
        text: The full text to extract from.
        match_position: Position of the matching term.
        match_length: Length of the matching term.
        max_chars: Maximum characters for the snippet.
        surrounding_context: Minimum context around the match.

    Returns:
        Tuple of (snippet_text, match_start_in_snippet, match_end_in_snippet).
    """
    if not text:
        return "", 0, 0

    # Calculate initial bounds with surrounding context
    initial_start = max(0, match_position - surrounding_context)
    initial_end = min(len(text), match_position + match_length + surrounding_context)

    # Try to expand to sentence boundaries
    sentence_start = find_sentence_start(text, initial_start, max_lookback=surrounding_context)
    sentence_end = find_sentence_end(text, initial_end, max_lookahead=surrounding_context)

    # If too long, trim to max_chars centered on match
    if sentence_end - sentence_start > max_chars:
        half_max = max_chars // 2
        center = match_position + (match_length // 2)
        sentence_start = max(0, center - half_max)
        sentence_end = min(len(text), center + half_max)

    # Extract snippet
    snippet = text[sentence_start:sentence_end].strip()

    # Calculate match position within snippet
    match_start_in_snippet = match_position - sentence_start
    match_end_in_snippet = match_start_in_snippet + match_length

    return snippet, match_start_in_snippet, match_end_in_snippet


def _find_markdown_link_regions(text: str) -> list[tuple[int, int]]:
    """Find regions in text that are inside markdown links.

    Returns a list of (start, end) tuples for regions that should NOT be highlighted.
    This includes both the link text [text] and the URL (url) parts.
    """
    # Match markdown links: [text](url)
    pattern = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
    return [(match.start(), match.end()) for match in pattern.finditer(text)]


def _is_inside_protected_region(start: int, end: int, protected_regions: list[tuple[int, int]]) -> bool:
    """Check if a match position overlaps with any protected region."""
    return any(start < region_end and end > region_start for region_start, region_end in protected_regions)


def highlight_terms_in_snippet(
    snippet: str,
    terms: Sequence[str],
    style: str = "plain",
    max_highlights: int = 3,
) -> str:
    """Highlight matching terms in a snippet.

    Args:
        snippet: The snippet text to highlight.
        terms: Terms to highlight.
        style: "plain" for [[term]] or "html" for <mark>term</mark>.
        max_highlights: Maximum number of terms to highlight.

    Returns:
        Snippet with highlighted terms.
    """
    if not snippet or not terms:
        return snippet

    # Find protected regions (markdown links) that should not be highlighted
    protected_regions = _find_markdown_link_regions(snippet)

    # Collect all matches with their positions
    matches: list[tuple[int, int, str]] = []  # (start, end, term)

    for term in terms:
        if not term or len(term) < 2:
            continue

        pattern = re.compile(re.escape(term), re.IGNORECASE)
        matches.extend((match.start(), match.end(), match.group(0)) for match in pattern.finditer(snippet))

    if not matches:
        return snippet

    # Sort by start position, then by length (longer matches first to prefer them)
    matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))

    # Remove overlapping matches and matches inside protected regions
    non_overlapping: list[tuple[int, int, str]] = []
    for start, end, matched_text in matches:
        # Skip matches inside markdown links
        if _is_inside_protected_region(start, end, protected_regions):
            continue

        # Check if this match overlaps with any already selected match
        overlaps = False
        for selected_start, selected_end, _ in non_overlapping:
            if start < selected_end and end > selected_start:
                overlaps = True
                break
        if not overlaps:
            non_overlapping.append((start, end, matched_text))
            if len(non_overlapping) >= max_highlights:
                break

    if not non_overlapping:
        return snippet

    # Apply highlights from end to start (to preserve positions)
    non_overlapping.sort(key=lambda x: x[0], reverse=True)
    result = snippet
    for start, end, matched_text in non_overlapping:
        replacement = f"<mark>{matched_text}</mark>" if style == "html" else f"[[{matched_text}]]"
        result = result[:start] + replacement + result[end:]

    return result


def build_smart_snippet(
    text: str,
    terms: Sequence[str],
    max_chars: int = 300,
    surrounding_context: int = 100,
    style: str = "plain",
) -> str:
    """Build a smart snippet with sentence awareness and highlighting.

    This is the main entry point for snippet generation.

    Args:
        text: The full text to extract snippet from.
        terms: Terms to find and highlight.
        max_chars: Maximum characters for the snippet.
        surrounding_context: Minimum context around matches.
        style: "plain" for [[term]] or "html" for <mark>term</mark>.

    Returns:
        A snippet with highlighted terms, respecting sentence boundaries.
    """
    if not text:
        return ""

    if not terms:
        # No terms, just return beginning of text
        return text[:max_chars].strip()

    # Find the first matching term
    text_lower = text.lower()
    best_match_pos = -1
    best_match_term = ""

    for term in terms:
        if not term:
            continue
        term_lower = term.lower()
        pos = text_lower.find(term_lower)
        if pos != -1 and (best_match_pos == -1 or pos < best_match_pos):
            best_match_pos = pos
            best_match_term = term

    if best_match_pos == -1:
        # No match found, return beginning of text
        return text[:max_chars].strip()

    # Extract snippet with sentence awareness
    snippet, _, _ = extract_sentence_snippet(
        text,
        best_match_pos,
        len(best_match_term),
        max_chars=max_chars,
        surrounding_context=surrounding_context,
    )

    # Highlight all matching terms
    return highlight_terms_in_snippet(snippet, terms, style=style)
