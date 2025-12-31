"""Phrase proximity scoring for multi-word queries.

This module provides utilities for calculating phrase proximity bonuses
when query terms appear adjacent or near each other in documents.

The phrase bonus is a smart default that rewards exact or near-exact
phrase matches without requiring per-tenant configuration.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def get_min_span(term_positions: Mapping[str, Sequence[int]]) -> float:
    """Calculate minimum span containing at least one of each term.

    The span is the number of positions from first to last term inclusive.
    For adjacent terms, span equals the number of terms.

    Args:
        term_positions: Dictionary mapping terms to their positions.

    Returns:
        Minimum span, or infinity if not all terms are present.
    """
    if not term_positions:
        return float("inf")

    term_count = len(term_positions)
    if term_count == 1:
        return 1.0

    # Get all position lists
    position_lists = list(term_positions.values())

    # Find minimum span using a sliding window approach
    # For each combination of positions, calculate the span
    min_span = float("inf")

    # Use greedy approach: for each position of first term,
    # find closest positions of other terms
    first_term_positions = position_lists[0]

    for anchor in first_term_positions:
        # For this anchor, find the closest position of each other term
        span_positions = [anchor]
        for other_positions in position_lists[1:]:
            # Find position closest to anchor
            closest = min(other_positions, key=lambda p: abs(p - anchor))
            span_positions.append(closest)

        # Calculate span for this combination
        span = max(span_positions) - min(span_positions) + 1
        min_span = min(min_span, span)

    return min_span
