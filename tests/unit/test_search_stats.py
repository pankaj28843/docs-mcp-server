"""Unit tests for search stats helpers."""

from __future__ import annotations

from docs_mcp_server.search.stats import (
    FieldLengthStats,
    bm25,
    calculate_idf,
    compute_field_length_stats,
)


def test_compute_field_length_stats_returns_averages() -> None:
    stats = compute_field_length_stats(
        {
            "body": {"doc1": 100, "doc2": 50},
            "title": {"doc1": 5},
        }
    )

    assert isinstance(stats["body"], FieldLengthStats)
    assert stats["body"].document_count == 2
    assert stats["body"].average_length == 75
    assert stats["title"].average_length == 5


def test_calculate_idf_handles_small_doc_counts() -> None:
    idf_high = calculate_idf(doc_freq=1, total_docs=10)
    idf_low = calculate_idf(doc_freq=5, total_docs=10)

    assert idf_high > idf_low > 0


def test_bm25_respects_term_frequency() -> None:
    tf_one = bm25(tf=1, doc_length=100, avg_doc_length=80)
    tf_three = bm25(tf=3, doc_length=100, avg_doc_length=80)

    assert tf_three > tf_one
