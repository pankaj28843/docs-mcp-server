"""Tests for bloom filter optimization."""

import math
import threading

from docs_mcp_server.search.bloom_filter import BloomFilter, BloomFilterOptimizer


class TestBloomFilter:
    """Test bloom filter functionality."""

    def test_init_calculates_optimal_parameters(self):
        """Test bloom filter initialization calculates correct parameters."""
        bf = BloomFilter(expected_items=1000, false_positive_rate=0.01)

        assert bf.expected_items == 1000
        assert bf.false_positive_rate == 0.01
        assert bf.bit_size > 0
        assert bf.hash_count > 0
        assert bf.item_count == 0
        assert len(bf.bit_array) > 0

    def test_calculate_bit_size_formula(self):
        """Test bit size calculation follows correct formula."""
        bf = BloomFilter()

        # Test known values
        n, p = 1000, 0.01
        expected_size = int(-n * math.log(p) / (math.log(2) ** 2))
        actual_size = bf._calculate_bit_size(n, p)

        assert actual_size == expected_size

    def test_calculate_hash_count_formula(self):
        """Test hash count calculation follows correct formula."""
        bf = BloomFilter()

        # Test known values
        m, n = 9585, 1000  # Typical values
        expected_count = int(m / n * math.log(2))
        actual_count = bf._calculate_hash_count(m, n)

        assert actual_count == expected_count

    def test_hash_generates_different_values_with_seeds(self):
        """Test hash function generates different values with different seeds."""
        bf = BloomFilter()
        item = "test_item"

        hash1 = bf._hash(item, 0)
        hash2 = bf._hash(item, 1)
        hash3 = bf._hash(item, 2)

        # Different seeds should produce different hashes
        assert hash1 != hash2
        assert hash2 != hash3
        assert hash1 != hash3

        # All hashes should be within bit size
        assert 0 <= hash1 < bf.bit_size
        assert 0 <= hash2 < bf.bit_size
        assert 0 <= hash3 < bf.bit_size

    def test_hash_is_deterministic(self):
        """Test hash function is deterministic."""
        bf = BloomFilter()
        item = "test_item"
        seed = 42

        hash1 = bf._hash(item, seed)
        hash2 = bf._hash(item, seed)

        assert hash1 == hash2

    def test_add_item_sets_bits(self):
        """Test adding item sets appropriate bits."""
        bf = BloomFilter(expected_items=100, false_positive_rate=0.01)
        initial_bits = bf.bit_array[:]

        bf.add("test_item")

        # Some bits should have changed
        assert bf.bit_array != initial_bits
        assert bf.item_count == 1

    def test_contains_returns_true_for_added_items(self):
        """Test contains returns True for items that were added."""
        bf = BloomFilter(expected_items=100, false_positive_rate=0.01)

        items = ["apple", "banana", "cherry", "date"]

        for item in items:
            bf.add(item)

        # All added items should be found (no false negatives)
        for item in items:
            assert bf.contains(item) is True

    def test_contains_may_return_false_positives(self):
        """Test contains may return false positives but never false negatives."""
        bf = BloomFilter(expected_items=10, false_positive_rate=0.1)

        # Add some items
        added_items = ["item1", "item2", "item3"]
        for item in added_items:
            bf.add(item)

        # Test many items that weren't added
        false_positives = 0
        test_items = [f"not_added_{i}" for i in range(100)]

        for item in test_items:
            if bf.contains(item):
                false_positives += 1

        # Should have some false positives (but not too many)
        # With 0.1 false positive rate, expect around 10% false positives
        assert 0 <= false_positives <= 50  # Allow some variance

    def test_contains_no_false_negatives(self):
        """Test contains never returns false negatives."""
        bf = BloomFilter(expected_items=1000, false_positive_rate=0.01)

        # Add many items
        items = [f"item_{i}" for i in range(100)]
        for item in items:
            bf.add(item)

        # All added items must be found
        for item in items:
            assert bf.contains(item) is True, f"False negative for {item}"

    def test_get_stats_returns_correct_info(self):
        """Test get_stats returns correct statistics."""
        bf = BloomFilter(expected_items=500, false_positive_rate=0.02)

        # Add some items
        for i in range(10):
            bf.add(f"item_{i}")

        stats = bf.get_stats()

        assert stats["bit_size"] == bf.bit_size
        assert stats["hash_count"] == bf.hash_count
        assert stats["item_count"] == 10
        assert stats["memory_bytes"] == len(bf.bit_array)
        assert stats["expected_false_positive_rate"] == 0.02

    def test_bit_manipulation_correctness(self):
        """Test bit manipulation operations are correct."""
        bf = BloomFilter(expected_items=100, false_positive_rate=0.01)

        # Test specific bit operations
        item = "test_bit_ops"

        # Get hash positions before adding
        positions = []
        for i in range(bf.hash_count):
            bit_index = bf._hash(item, i)
            positions.append(bit_index)

        # Add item
        bf.add(item)

        # Check that all positions are set
        for bit_index in positions:
            byte_index = bit_index // 8
            bit_offset = bit_index % 8
            assert bf.bit_array[byte_index] & (1 << bit_offset) != 0

    def test_empty_filter_contains_nothing(self):
        """Test empty bloom filter contains no items."""
        bf = BloomFilter(expected_items=100, false_positive_rate=0.01)

        # Empty filter should not contain any items
        test_items = ["test1", "test2", "test3", ""]
        for item in test_items:
            assert bf.contains(item) is False

    def test_case_sensitivity_in_hash(self):
        """Test hash function is case sensitive."""
        bf = BloomFilter()

        hash_lower = bf._hash("test", 0)
        hash_upper = bf._hash("TEST", 0)

        # Case should matter in hashing
        assert hash_lower != hash_upper

    def test_large_item_count_tracking(self):
        """Test item count is tracked correctly for many items."""
        bf = BloomFilter(expected_items=1000, false_positive_rate=0.01)

        num_items = 500
        for i in range(num_items):
            bf.add(f"item_{i}")

        assert bf.item_count == num_items


class TestBloomFilterOptimizer:
    """Test bloom filter optimizer functionality."""

    def test_init_creates_empty_optimizer(self):
        """Test optimizer initialization."""
        optimizer = BloomFilterOptimizer()

        assert optimizer.vocabulary_filter is None
        assert optimizer.stats["queries_filtered"] == 0
        assert optimizer.stats["queries_processed"] == 0
        assert optimizer.stats["terms_filtered"] == 0
        assert optimizer.stats["terms_processed"] == 0

    def test_build_vocabulary_filter_creates_bloom_filter(self):
        """Test building vocabulary filter creates bloom filter."""
        optimizer = BloomFilterOptimizer()
        vocabulary = ["apple", "banana", "cherry", "date", "elderberry"]

        optimizer.build_vocabulary_filter(vocabulary)

        assert optimizer.vocabulary_filter is not None
        assert isinstance(optimizer.vocabulary_filter, BloomFilter)
        assert optimizer.vocabulary_filter.item_count == len(vocabulary)

    def test_build_vocabulary_filter_empty_vocabulary(self):
        """Test building filter with empty vocabulary."""
        optimizer = BloomFilterOptimizer()

        optimizer.build_vocabulary_filter([])

        assert optimizer.vocabulary_filter is None

    def test_build_vocabulary_filter_lowercases_terms(self):
        """Test vocabulary filter lowercases terms."""
        optimizer = BloomFilterOptimizer()
        vocabulary = ["Apple", "BANANA", "CheRRy"]

        optimizer.build_vocabulary_filter(vocabulary)

        # Should find lowercase versions
        assert optimizer.vocabulary_filter.contains("apple")
        assert optimizer.vocabulary_filter.contains("banana")
        assert optimizer.vocabulary_filter.contains("cherry")

    def test_filter_query_terms_without_filter(self):
        """Test filtering terms when no filter is built."""
        optimizer = BloomFilterOptimizer()
        terms = ["apple", "banana", "cherry"]

        result = optimizer.filter_query_terms(terms)

        # Should return all terms unchanged
        assert result == terms

    def test_filter_query_terms_with_filter(self):
        """Test filtering terms with vocabulary filter."""
        optimizer = BloomFilterOptimizer()
        vocabulary = ["apple", "banana", "cherry"]
        optimizer.build_vocabulary_filter(vocabulary)

        # Test with mix of vocabulary and non-vocabulary terms
        query_terms = ["apple", "unknown", "banana", "missing"]
        result = optimizer.filter_query_terms(query_terms)

        # Should keep vocabulary terms, may keep some non-vocabulary (false positives)
        assert "apple" in result
        assert "banana" in result
        # "unknown" and "missing" may or may not be in result (false positives possible)

    def test_filter_query_terms_updates_stats(self):
        """Test filtering updates statistics correctly."""
        optimizer = BloomFilterOptimizer()
        vocabulary = ["apple", "banana", "cherry"]
        optimizer.build_vocabulary_filter(vocabulary)

        terms = ["apple", "unknown"]
        optimizer.filter_query_terms(terms)

        assert optimizer.stats["queries_processed"] == 1
        assert optimizer.stats["terms_processed"] == 2

    def test_filter_query_terms_case_insensitive(self):
        """Test filtering is case insensitive."""
        optimizer = BloomFilterOptimizer()
        vocabulary = ["apple", "banana"]
        optimizer.build_vocabulary_filter(vocabulary)

        # Test with different cases
        terms = ["Apple", "BANANA", "Cherry"]
        result = optimizer.filter_query_terms(terms)

        # Should find Apple and BANANA (case insensitive)
        assert "Apple" in result
        assert "BANANA" in result

    def test_get_performance_info_without_filter(self):
        """Test performance info when no filter is built."""
        optimizer = BloomFilterOptimizer()

        info = optimizer.get_performance_info()

        assert info["bloom_filter_enabled"] is False
        assert info["optimization_type"] == "bloom_filter_vocabulary"
        assert "bit_size" not in info

    def test_get_performance_info_with_filter(self):
        """Test performance info with filter and stats."""
        optimizer = BloomFilterOptimizer()
        vocabulary = ["apple", "banana", "cherry"]
        optimizer.build_vocabulary_filter(vocabulary)

        # Process some queries to generate stats
        optimizer.filter_query_terms(["apple", "unknown"])
        optimizer.filter_query_terms(["banana", "missing", "absent"])

        info = optimizer.get_performance_info()

        assert info["bloom_filter_enabled"] is True
        assert info["optimization_type"] == "bloom_filter_vocabulary"
        assert "bit_size" in info
        assert "hash_count" in info
        assert "item_count" in info
        assert "queries_processed" in info
        assert "terms_processed" in info

    def test_get_performance_info_calculates_rates(self):
        """Test performance info calculates filter rates."""
        optimizer = BloomFilterOptimizer()
        vocabulary = ["apple"]
        optimizer.build_vocabulary_filter(vocabulary)

        # Process queries with known filtering
        optimizer.filter_query_terms(["apple"])  # No filtering
        optimizer.filter_query_terms(["unknown"])  # Should filter

        info = optimizer.get_performance_info()

        # Should have calculated rates
        assert "term_filter_rate" in info
        assert "query_filter_rate" in info
        assert 0 <= info["term_filter_rate"] <= 1
        assert 0 <= info["query_filter_rate"] <= 1

    def test_realistic_vocabulary_filtering(self):
        """Test realistic vocabulary filtering scenario."""
        optimizer = BloomFilterOptimizer()

        # Build vocabulary with common programming terms
        vocabulary = [
            "function",
            "class",
            "method",
            "variable",
            "import",
            "export",
            "async",
            "await",
            "promise",
            "callback",
            "event",
            "handler",
            "component",
            "props",
            "state",
            "render",
            "lifecycle",
            "hook",
        ]
        optimizer.build_vocabulary_filter(vocabulary)

        # Test queries with mix of vocabulary and non-vocabulary terms
        test_queries = [
            ["function", "definition"],  # 1 vocab, 1 non-vocab
            ["class", "method", "property"],  # 2 vocab, 1 non-vocab
            ["unknown", "missing", "absent"],  # 0 vocab, 3 non-vocab
            ["async", "await", "promise"],  # 3 vocab, 0 non-vocab
        ]

        for query in test_queries:
            result = optimizer.filter_query_terms(query)

            # Should keep all vocabulary terms
            for term in query:
                if term in vocabulary:
                    assert term in result, f"Lost vocabulary term: {term}"

    def test_bloom_filter_memory_efficiency(self):
        """Test bloom filter is memory efficient."""
        optimizer = BloomFilterOptimizer()

        # Large vocabulary
        vocabulary = [f"term_{i}" for i in range(10000)]
        optimizer.build_vocabulary_filter(vocabulary)

        info = optimizer.get_performance_info()

        # Memory usage should be reasonable (much less than storing all terms)
        memory_bytes = info["memory_bytes"]

        # Rough estimate: storing 10k terms as strings would be ~100KB+
        # Bloom filter should be much smaller
        assert memory_bytes < 50000  # Less than 50KB for 10k terms

    def test_false_positive_rate_approximation(self):
        """Test actual false positive rate is approximately as expected."""
        optimizer = BloomFilterOptimizer()

        # Small vocabulary for controlled testing
        vocabulary = ["apple", "banana", "cherry"]
        optimizer.build_vocabulary_filter(vocabulary)

        # Test many non-vocabulary terms
        false_positives = 0
        test_count = 1000

        for i in range(test_count):
            test_term = f"nonvocab_{i}"
            if optimizer.vocabulary_filter.contains(test_term):
                false_positives += 1

        actual_rate = false_positives / test_count
        expected_rate = 0.01  # 1% configured rate

        # Allow some variance (should be roughly in expected range)
        assert 0 <= actual_rate <= 0.1  # Should be low but allow variance

    def test_concurrent_access_safety(self):
        """Test bloom filter operations are safe for concurrent access."""
        optimizer = BloomFilterOptimizer()
        vocabulary = [f"term_{i}" for i in range(100)]
        optimizer.build_vocabulary_filter(vocabulary)

        results = {}

        def worker(worker_id):
            # Each worker performs filtering operations
            terms = [f"term_{i}" for i in range(10)] + [f"unknown_{worker_id}"]
            result = optimizer.filter_query_terms(terms)
            results[worker_id] = len(result)

        # Run multiple workers concurrently
        threads = []
        for i in range(5):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # All workers should complete successfully
        assert len(results) == 5

        # Results should be consistent (all vocabulary terms found)
        for result_count in results.values():
            assert result_count >= 10  # At least the 10 vocabulary terms
