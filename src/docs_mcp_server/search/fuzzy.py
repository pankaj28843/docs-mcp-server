"""Fuzzy matching for typo-tolerant search.

This module provides edit distance calculation and fuzzy term matching
for handling typos in search queries.

Smart Defaults (no per-tenant config needed):
- Max edit distance of 1 for short terms (3-5 chars)
- Max edit distance of 2 for longer terms (6+ chars)
- No fuzzy matching for very short terms (1-2 chars)
- Preserves exact matches with higher priority
"""

from __future__ import annotations

from collections.abc import Sequence


def levenshtein_distance(s1: str, s2: str, max_distance: int | None = None) -> int:
    """Calculate the Levenshtein (edit) distance between two strings.

    Uses dynamic programming for O(m*n) time complexity, with optional
    early termination when distance exceeds max_distance.

    Args:
        s1: First string.
        s2: Second string.
        max_distance: If provided, return max_distance+1 early when
            distance is guaranteed to exceed this threshold.

    Returns:
        The minimum number of single-character edits (insertions,
        deletions, substitutions) needed to change s1 into s2.
        If max_distance is set and exceeded, returns max_distance+1.

    Examples:
        >>> levenshtein_distance("kitten", "sitting")
        3
        >>> levenshtein_distance("hello", "hallo")
        1
        >>> levenshtein_distance("", "abc")
        3
    """
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)

    # Use shorter string as columns for space efficiency
    if len(s1) > len(s2):
        s1, s2 = s2, s1

    m, n = len(s1), len(s2)

    # Early check: if length difference exceeds max_distance, skip
    if max_distance is not None and abs(m - n) > max_distance:
        return max_distance + 1

    # Only need two rows at a time
    prev_row = list(range(m + 1))
    curr_row = [0] * (m + 1)

    for j in range(1, n + 1):
        curr_row[0] = j
        row_min = curr_row[0]  # Track minimum in current row for early exit
        for i in range(1, m + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            curr_row[i] = min(
                prev_row[i] + 1,  # deletion
                curr_row[i - 1] + 1,  # insertion
                prev_row[i - 1] + cost,  # substitution
            )
            row_min = min(row_min, curr_row[i])

        # Early termination: if minimum possible distance exceeds max, bail out
        if max_distance is not None and row_min > max_distance:
            return max_distance + 1

        prev_row, curr_row = curr_row, prev_row

    return prev_row[m]


def get_max_edit_distance(term_length: int) -> int:
    """Get the maximum allowed edit distance for a term based on its length.

    Smart defaults:
    - 1-2 chars: No fuzzy matching (too many false positives)
    - 3-5 chars: Max 1 edit
    - 6+ chars: Max 2 edits

    Args:
        term_length: Length of the search term.

    Returns:
        Maximum allowed edit distance.
    """
    if term_length <= 2:
        return 0  # No fuzzy for very short terms
    if term_length <= 5:
        return 1  # 1 typo for short terms
    return 2  # 2 typos for longer terms


def find_fuzzy_matches(
    query_term: str,
    vocabulary: Sequence[str],
    max_distance: int | None = None,
) -> list[tuple[str, int]]:
    """Find terms in vocabulary that fuzzy-match the query term.

    Args:
        query_term: The term to match (may contain typo).
        vocabulary: List of valid terms to match against.
        max_distance: Maximum edit distance allowed. If None, uses
            smart default based on term length.

    Returns:
        List of (matching_term, edit_distance) tuples, sorted by
        edit distance (closest matches first). Exact matches have
        distance 0.
    """
    if not query_term or not vocabulary:
        return []

    query_lower = query_term.lower()

    if max_distance is None:
        max_distance = get_max_edit_distance(len(query_term))

    if max_distance == 0:
        # No fuzzy matching, only exact matches
        for term in vocabulary:
            if term.lower() == query_lower:
                return [(term, 0)]
        return []

    matches: list[tuple[str, int]] = []

    for term in vocabulary:
        term_lower = term.lower()

        # Quick check: if length difference exceeds max_distance, skip
        if abs(len(query_lower) - len(term_lower)) > max_distance:
            continue

        distance = levenshtein_distance(query_lower, term_lower, max_distance)
        if distance <= max_distance:
            matches.append((term, distance))

    # Sort by distance (exact matches first), then alphabetically
    matches.sort(key=lambda x: (x[1], x[0].lower()))

    return matches
