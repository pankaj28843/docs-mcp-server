"""Phrase proximity scoring for multi-word queries.

This module provides utilities for calculating phrase proximity bonuses
when query terms appear adjacent or near each other in documents.

The phrase bonus is a smart default that rewards exact or near-exact
phrase matches without requiring per-tenant configuration.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import heapq


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

    # Find minimum span using a k-way merge window (O(N log k))
    min_span = float("inf")
    heap: list[tuple[int, int, int]] = []
    max_pos = float("-inf")

    for list_idx, positions in enumerate(position_lists):
        if not positions:
            return float("inf")
        pos = positions[0]
        heapq.heappush(heap, (pos, list_idx, 0))
        max_pos = max(max_pos, pos)

    while heap:
        min_pos, list_idx, pos_idx = heapq.heappop(heap)
        span = max_pos - min_pos + 1
        min_span = min(min_span, span)

        next_idx = pos_idx + 1
        if next_idx >= len(position_lists[list_idx]):
            break
        next_pos = position_lists[list_idx][next_idx]
        heapq.heappush(heap, (next_pos, list_idx, next_idx))
        max_pos = max(max_pos, next_pos)

    return min_span
