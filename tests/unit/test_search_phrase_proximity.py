"""Unit tests for phrase proximity scoring.

Phrase proximity scoring rewards documents where query terms appear
adjacent or near each other, improving results for multi-word queries.
"""

import pytest

from docs_mcp_server.search.phrase import get_min_span


@pytest.mark.unit
class TestGetMinSpan:
    """get_min_span calculates minimum window containing all terms."""

    def test_adjacent_terms_have_span_of_term_count(self):
        # Terms at positions 0, 1, 2 -> span is 3 (covering 3 terms)
        positions = {"a": [0], "b": [1], "c": [2]}
        span = get_min_span(positions)
        assert span == 3

    def test_separated_terms_have_larger_span(self):
        # "a" at 0, "b" at 5 -> span is 6 (positions 0-5 inclusive)
        positions = {"a": [0], "b": [5]}
        span = get_min_span(positions)
        assert span == 6

    def test_multiple_occurrences_finds_minimum(self):
        # "a" at [0, 10], "b" at [2, 15]
        # Best: a=0, b=2 -> span=3
        positions = {"a": [0, 10], "b": [2, 15]}
        span = get_min_span(positions)
        assert span == 3

    def test_empty_positions_returns_infinity(self):
        positions: dict[str, list[int]] = {}
        span = get_min_span(positions)
        assert span == float("inf")

    def test_single_term_returns_one(self):
        positions = {"a": [5]}
        span = get_min_span(positions)
        assert span == 1
