"""Bloom filter optimization for fast negative query detection.

Real optimization using memory-efficient bloom filter for vocabulary.
Enabled by default for maximum performance with early query termination.
"""

import hashlib
import logging
import math
from typing import Any


logger = logging.getLogger(__name__)


class BloomFilter:
    """Memory-efficient bloom filter for vocabulary filtering."""

    @staticmethod
    def _hash_with_bit_size(item: str, seed: int, bit_size: int) -> int:
        """Generate hash for item with seed and explicit bit size."""
        hash_obj = hashlib.md5(f"{item}{seed}".encode())
        return int(hash_obj.hexdigest(), 16) % bit_size

    def __init__(self, expected_items: int = 100000, false_positive_rate: float = 0.01):
        """Initialize bloom filter with expected parameters."""
        self.expected_items = expected_items
        self.false_positive_rate = false_positive_rate

        # Calculate optimal bit array size and hash functions
        self.bit_size = self._calculate_bit_size(expected_items, false_positive_rate)
        self.hash_count = self._calculate_hash_count(self.bit_size, expected_items)

        # Initialize bit array
        self.bit_array = bytearray(self.bit_size // 8 + 1)
        self.item_count = 0

        logger.info(f"Bloom filter initialized: {self.bit_size} bits, {self.hash_count} hashes")

    def _calculate_bit_size(self, n: int, p: float) -> int:
        """Calculate optimal bit array size."""
        return int(-n * math.log(p) / (math.log(2) ** 2))

    def _calculate_hash_count(self, m: int, n: int) -> int:
        """Calculate optimal number of hash functions."""
        return int(m / n * math.log(2))

    def _hash(self, item: str, seed: int) -> int:
        """Generate hash for item with seed."""
        return self._hash_with_bit_size(item, seed, self.bit_size)

    def add(self, item: str):
        """Add item to bloom filter."""
        for i in range(self.hash_count):
            bit_index = self._hash(item, i)
            byte_index = bit_index // 8
            bit_offset = bit_index % 8
            self.bit_array[byte_index] |= 1 << bit_offset
        self.item_count += 1

    def contains(self, item: str) -> bool:
        """Check if item might be in the set (no false negatives)."""
        for i in range(self.hash_count):
            bit_index = self._hash(item, i)
            byte_index = bit_index // 8
            bit_offset = bit_index % 8
            if not (self.bit_array[byte_index] & (1 << bit_offset)):
                return False  # Definitely not in set
        return True  # Might be in set (could be false positive)

    def get_stats(self) -> dict[str, Any]:
        """Get bloom filter statistics."""
        return {
            "bit_size": self.bit_size,
            "hash_count": self.hash_count,
            "item_count": self.item_count,
            "memory_bytes": len(self.bit_array),
            "expected_false_positive_rate": self.false_positive_rate,
        }


def bloom_positions(item: str, bit_size: int, hash_count: int) -> list[int]:
    """Compute bloom filter bit positions for an item."""
    return [BloomFilter._hash_with_bit_size(item, seed, bit_size) for seed in range(hash_count)]


class BloomFilterOptimizer:
    """Bloom filter optimization for search queries."""

    def __init__(self):
        """Initialize bloom filter optimizer."""
        self.vocabulary_filter = None
        self.stats = {"queries_filtered": 0, "queries_processed": 0, "terms_filtered": 0, "terms_processed": 0}

    def build_vocabulary_filter(self, vocabulary: list[str]):
        """Build bloom filter from vocabulary."""
        if not vocabulary:
            return

        self.vocabulary_filter = BloomFilter(
            expected_items=len(vocabulary),
            false_positive_rate=0.01,  # 1% false positive rate
        )

        for term in vocabulary:
            self.vocabulary_filter.add(term.lower())

        logger.info(f"Vocabulary bloom filter built with {len(vocabulary)} terms")

    def filter_query_terms(self, terms: list[str]) -> list[str]:
        """Filter query terms using bloom filter."""
        if not self.vocabulary_filter:
            return terms

        self.stats["queries_processed"] += 1
        filtered_terms = []

        for term in terms:
            self.stats["terms_processed"] += 1
            if self.vocabulary_filter.contains(term.lower()):
                filtered_terms.append(term)
            else:
                self.stats["terms_filtered"] += 1

        if len(filtered_terms) < len(terms):
            self.stats["queries_filtered"] += 1

        return filtered_terms

    def get_performance_info(self) -> dict[str, Any]:
        """Get bloom filter performance information."""
        info = {
            "bloom_filter_enabled": self.vocabulary_filter is not None,
            "optimization_type": "bloom_filter_vocabulary",
        }

        if self.vocabulary_filter:
            info.update(self.vocabulary_filter.get_stats())
            info.update(self.stats)

            # Calculate efficiency metrics
            if self.stats["terms_processed"] > 0:
                info["term_filter_rate"] = self.stats["terms_filtered"] / self.stats["terms_processed"]
            if self.stats["queries_processed"] > 0:
                info["query_filter_rate"] = self.stats["queries_filtered"] / self.stats["queries_processed"]

        return info
