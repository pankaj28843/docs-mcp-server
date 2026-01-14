"""Tests for SIMD-optimized BM25 scoring."""

import math
from unittest.mock import patch

import numpy as np
import pytest

from docs_mcp_server.search.simd_bm25 import SIMDBm25Calculator


class TestSIMDBm25Calculator:
    """Test SIMD BM25 calculator functionality."""

    def test_init_default_parameters(self):
        """Test initialization with default parameters."""
        calc = SIMDBm25Calculator()
        assert calc.k1 == 1.2
        assert calc.b == 0.75
        assert isinstance(calc._simd_available, bool)

    def test_init_custom_parameters(self):
        """Test initialization with custom parameters."""
        calc = SIMDBm25Calculator(k1=1.5, b=0.8)
        assert calc.k1 == 1.5
        assert calc.b == 0.8

    def test_check_simd_support_with_numpy_success(self):
        """Test SIMD support detection when NumPy works."""
        calc = SIMDBm25Calculator()
        # Should work with normal NumPy installation
        assert calc._check_simd_support() is True

    @patch("numpy.log")
    def test_check_simd_support_numpy_failure(self, mock_log):
        """Test SIMD support detection when NumPy fails."""
        mock_log.side_effect = Exception("NumPy error")
        calc = SIMDBm25Calculator()
        assert calc._check_simd_support() is False

    def test_calculate_scores_scalar_basic(self):
        """Test scalar BM25 calculation with basic inputs."""
        calc = SIMDBm25Calculator()

        term_frequencies = [2, 1, 3]
        doc_frequencies = [5, 3, 7]
        doc_lengths = [100, 150, 80]
        avg_doc_length = 110.0
        total_docs = 1000

        scores = calc._calculate_scores_scalar(
            term_frequencies, doc_frequencies, doc_lengths, avg_doc_length, total_docs
        )

        assert len(scores) == 3
        assert all(isinstance(score, float) for score in scores)
        assert all(score > 0 for score in scores)  # All should be positive

    def test_calculate_scores_scalar_edge_cases(self):
        """Test scalar calculation with edge cases."""
        calc = SIMDBm25Calculator()

        # Single document
        scores = calc._calculate_scores_scalar([1], [1], [50], 50.0, 1)
        assert len(scores) == 1
        assert isinstance(scores[0], float)

        # Zero term frequency
        scores = calc._calculate_scores_scalar([0], [1], [50], 50.0, 10)
        assert scores[0] == 0.0

    def test_calculate_scores_vectorized_small_dataset_fallback(self):
        """Test vectorized calculation falls back for small datasets."""
        calc = SIMDBm25Calculator()

        # Small dataset (< 10 items) should use scalar fallback
        term_frequencies = [2, 1]
        doc_frequencies = [5, 3]
        doc_lengths = [100, 150]
        avg_doc_length = 125.0
        total_docs = 1000

        with patch.object(calc, "_calculate_scores_scalar") as mock_scalar:
            mock_scalar.return_value = [1.0, 2.0]

            scores = calc.calculate_scores_vectorized(
                term_frequencies, doc_frequencies, doc_lengths, avg_doc_length, total_docs
            )

            mock_scalar.assert_called_once()
            assert scores == [1.0, 2.0]

    def test_calculate_scores_vectorized_no_simd_fallback(self):
        """Test vectorized calculation falls back when SIMD unavailable."""
        calc = SIMDBm25Calculator()
        calc._simd_available = False

        term_frequencies = [2, 1, 3, 4, 5, 6, 7, 8, 9, 10]  # >= 10 items
        doc_frequencies = [5, 3, 7, 8, 9, 10, 11, 12, 13, 14]
        doc_lengths = [100] * 10
        avg_doc_length = 100.0
        total_docs = 1000

        with patch.object(calc, "_calculate_scores_scalar") as mock_scalar:
            mock_scalar.return_value = [1.0] * 10

            scores = calc.calculate_scores_vectorized(
                term_frequencies, doc_frequencies, doc_lengths, avg_doc_length, total_docs
            )

            mock_scalar.assert_called_once()
            assert len(scores) == 10

    def test_calculate_scores_vectorized_simd_success(self):
        """Test successful SIMD vectorized calculation."""
        calc = SIMDBm25Calculator()
        calc._simd_available = True

        term_frequencies = [2, 1, 3, 4, 5, 6, 7, 8, 9, 10]  # >= 10 items
        doc_frequencies = [5, 3, 7, 8, 9, 10, 11, 12, 13, 14]
        doc_lengths = [100, 150, 80, 120, 90, 110, 130, 70, 160, 95]
        avg_doc_length = 110.0
        total_docs = 1000

        scores = calc.calculate_scores_vectorized(
            term_frequencies, doc_frequencies, doc_lengths, avg_doc_length, total_docs
        )

        assert len(scores) == 10
        assert all(isinstance(score, float) for score in scores)
        # Verify scores are reasonable (positive for typical BM25)
        assert all(score > 0 for score in scores)

    @patch("numpy.array")
    def test_calculate_scores_vectorized_numpy_exception(self, mock_array):
        """Test vectorized calculation handles NumPy exceptions."""
        mock_array.side_effect = Exception("NumPy error")

        calc = SIMDBm25Calculator()
        calc._simd_available = True

        term_frequencies = [2, 1, 3, 4, 5, 6, 7, 8, 9, 10]
        doc_frequencies = [5, 3, 7, 8, 9, 10, 11, 12, 13, 14]
        doc_lengths = [100] * 10
        avg_doc_length = 100.0
        total_docs = 1000

        with patch.object(calc, "_calculate_scores_scalar") as mock_scalar:
            mock_scalar.return_value = [1.0] * 10

            scores = calc.calculate_scores_vectorized(
                term_frequencies, doc_frequencies, doc_lengths, avg_doc_length, total_docs
            )

            mock_scalar.assert_called_once()
            assert len(scores) == 10

    def test_vectorized_vs_scalar_consistency(self):
        """Test that vectorized and scalar calculations produce similar results."""
        calc = SIMDBm25Calculator()
        calc._simd_available = True

        term_frequencies = [2, 1, 3, 4, 5, 6, 7, 8, 9, 10]
        doc_frequencies = [5, 3, 7, 8, 9, 10, 11, 12, 13, 14]
        doc_lengths = [100, 150, 80, 120, 90, 110, 130, 70, 160, 95]
        avg_doc_length = 110.0
        total_docs = 1000

        # Get vectorized scores
        vectorized_scores = calc.calculate_scores_vectorized(
            term_frequencies, doc_frequencies, doc_lengths, avg_doc_length, total_docs
        )

        # Get scalar scores
        scalar_scores = calc._calculate_scores_scalar(
            term_frequencies, doc_frequencies, doc_lengths, avg_doc_length, total_docs
        )

        # Should be very close (within floating point precision)
        assert len(vectorized_scores) == len(scalar_scores)
        for v_score, s_score in zip(vectorized_scores, scalar_scores, strict=True):
            assert abs(v_score - s_score) < 1e-6

    def test_get_performance_info_simd_available(self):
        """Test performance info when SIMD is available."""
        calc = SIMDBm25Calculator()
        calc._simd_available = True

        info = calc.get_performance_info()

        assert info["simd_available"] is True
        assert info["numpy_version"] == np.__version__
        assert info["optimization_type"] == "simd_vectorized"

    def test_get_performance_info_simd_unavailable(self):
        """Test performance info when SIMD is unavailable."""
        calc = SIMDBm25Calculator()
        calc._simd_available = False

        info = calc.get_performance_info()

        assert info["simd_available"] is False
        assert info["numpy_version"] is None
        assert info["optimization_type"] == "scalar_fallback"

    def test_bm25_formula_correctness(self):
        """Test that BM25 formula is implemented correctly."""
        calc = SIMDBm25Calculator(k1=1.2, b=0.75)

        # Single document test with known values
        tf = 3  # term frequency
        df = 5  # document frequency
        dl = 100  # document length
        avg_dl = 80.0  # average document length
        total_docs = 1000

        scores = calc._calculate_scores_scalar([tf], [df], [dl], avg_dl, total_docs)

        # Manual calculation for verification
        expected_idf = math.log((total_docs - df + 0.5) / (df + 0.5))
        expected_tf_norm = (tf * (calc.k1 + 1)) / (tf + calc.k1 * (1 - calc.b + calc.b * (dl / avg_dl)))
        expected_score = expected_idf * expected_tf_norm

        assert abs(scores[0] - expected_score) < 1e-10

    def test_empty_inputs(self):
        """Test handling of empty inputs."""
        calc = SIMDBm25Calculator()

        scores = calc._calculate_scores_scalar([], [], [], 100.0, 1000)
        assert scores == []

        scores = calc.calculate_scores_vectorized([], [], [], 100.0, 1000)
        assert scores == []

    def test_mismatched_input_lengths(self):
        """Test handling of mismatched input lengths."""
        calc = SIMDBm25Calculator()

        # This should raise an exception due to strict=True in zip
        with pytest.raises(ValueError, match=r"zip\(\) argument .* is shorter than"):
            calc._calculate_scores_scalar([1, 2], [1], [100, 150], 125.0, 1000)

    def test_zero_document_frequency_edge_case(self):
        """Test handling of zero document frequency (edge case)."""
        calc = SIMDBm25Calculator()

        # df=0 would cause log(inf) in IDF calculation
        # The implementation should handle this gracefully
        scores = calc._calculate_scores_scalar([1], [0], [100], 100.0, 1000)
        assert len(scores) == 1
        # With df=0, IDF should be very high (positive)
        assert scores[0] > 0

    def test_very_large_inputs(self):
        """Test handling of very large input values."""
        calc = SIMDBm25Calculator()

        # Test with large values
        large_tf = [1000000]
        large_df = [500000]
        large_dl = [10000000]
        large_avg_dl = 5000000.0
        large_total_docs = 10000000

        scores = calc._calculate_scores_scalar(large_tf, large_df, large_dl, large_avg_dl, large_total_docs)

        assert len(scores) == 1
        assert isinstance(scores[0], float)
        assert not math.isnan(scores[0])
        assert not math.isinf(scores[0])
