"""Statistical helpers for BM25 style scoring.

The functions here stay independent of any storage backend so they can be
reused across different storage implementations. They intentionally cover
only a small subset of BM25 so we can unit test behavior before wiring
it into the query planner.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class FieldLengthStats:
    """Aggregated term statistics for a field."""

    field: str
    total_terms: int
    document_count: int

    @property
    def average_length(self) -> float:
        if self.document_count == 0:
            return 0.0
        return self.total_terms / self.document_count


def compute_field_length_stats(field_lengths: Mapping[str, Mapping[str, int]]) -> dict[str, FieldLengthStats]:
    """Return aggregate stats for each field given per-document lengths."""

    stats: dict[str, FieldLengthStats] = {}
    for field_name, lengths in field_lengths.items():
        doc_count = len(lengths)
        total_terms = sum(max(length, 0) for length in lengths.values())
        stats[field_name] = FieldLengthStats(
            field=field_name,
            total_terms=total_terms,
            document_count=doc_count,
        )
    return stats


def calculate_idf(doc_freq: int, total_docs: int, *, floor: float = 1e-6) -> float:
    """Return inverse document frequency with small-sample smoothing.

    Uses a floored IDF to ensure scores never go negative. This is a smart
    default that handles small corpora (e.g., 7 book chapters) gracefully.
    Common terms in small corpora receive near-zero IDF rather than negative.
    """

    if total_docs <= 0:
        return 0.0
    df = max(0, min(doc_freq, total_docs))
    numerator = total_docs - df + 0.5
    denominator = df + 0.5
    ratio = max(numerator / denominator, floor)
    raw_idf = math.log(ratio + floor) + 1.0
    # Ensure IDF is never negative (handles small corpora gracefully)
    return max(raw_idf, floor)


def bm25(tf: int, doc_length: int, avg_doc_length: float, *, k1: float = 1.5, b: float = 0.75) -> float:
    """Compute the BM25 term weight without IDF.

    Uses a capped length normalization to prevent very long documents
    (e.g., book chapters) from receiving excessive penalties. The cap
    limits dl/avgdl to 4x, meaning documents longer than 4x average
    are treated as 4x average for scoring purposes.
    """

    if tf <= 0:
        return 0.0
    # Cap the length ratio to prevent excessive penalties for very long docs
    # This is a smart default that handles book chapters (128KB) gracefully
    max_length_ratio = 4.0
    raw_ratio = doc_length / max(avg_doc_length, 1e-9)
    normalized_length = min(raw_ratio, max_length_ratio)
    denominator = tf + k1 * (1 - b + b * normalized_length)
    return (tf * (k1 + 1)) / denominator
