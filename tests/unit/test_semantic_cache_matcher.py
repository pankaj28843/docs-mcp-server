"""Unit tests for SemanticCacheMatcher.

Following Cosmic Python principles:
- Tests use minimal mocks (only embedding provider)
- Tests verify behavior, not implementation
- Tests cover edge cases and boundary conditions
"""

import logging
from unittest.mock import Mock

import pytest

from docs_mcp_server.domain.model import Content, Document, URL
from docs_mcp_server.services.semantic_cache_matcher import SemanticCacheMatcher


@pytest.fixture
def mock_embedding_provider():
    """Create mock embedding provider."""
    provider = Mock()
    provider.return_value = [0.5, 0.5, 0.5]  # Default embedding
    return provider


@pytest.fixture
def url_normalizer():
    """Simple URL normalizer for testing."""
    return lambda url: url.lower().replace("https://", "").replace("http://", "")


@pytest.fixture
def matcher(mock_embedding_provider):
    """Create SemanticCacheMatcher instance for testing."""
    return SemanticCacheMatcher(
        embedding_provider=mock_embedding_provider,
        similarity_threshold=0.7,
        return_limit=5,
    )


@pytest.mark.unit
class TestSemanticCacheMatcherInitialization:
    """Test SemanticCacheMatcher initialization."""

    def test_creates_matcher_with_config(self, matcher):
        """Test matcher can be created with configuration."""
        assert matcher is not None
        assert matcher.similarity_threshold == 0.7
        assert matcher.return_limit == 5


@pytest.mark.unit
class TestCosineSimilarityCalculation:
    """Test cosine similarity calculation edge cases."""

    def test_identical_vectors_return_one(self, matcher):
        """Test identical vectors have similarity of 1.0."""
        vec = [1.0, 2.0, 3.0]
        similarity = matcher._calculate_cosine_similarity(vec, vec)
        assert abs(similarity - 1.0) < 1e-10

    def test_orthogonal_vectors_return_zero(self, matcher):
        """Test orthogonal vectors have similarity of 0.0."""
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [0.0, 1.0, 0.0]
        similarity = matcher._calculate_cosine_similarity(vec1, vec2)
        assert abs(similarity) < 1e-10

    def test_empty_first_vector_returns_zero(self, matcher):
        """Test empty first vector returns 0.0."""
        similarity = matcher._calculate_cosine_similarity([], [1.0, 2.0])
        assert similarity == 0.0

    def test_empty_second_vector_returns_zero(self, matcher):
        """Test empty second vector returns 0.0."""
        similarity = matcher._calculate_cosine_similarity([1.0, 2.0], [])
        assert similarity == 0.0

    def test_zero_magnitude_first_vector_returns_zero(self, matcher):
        """Test zero magnitude first vector returns 0.0."""
        similarity = matcher._calculate_cosine_similarity([0.0, 0.0], [1.0, 2.0])
        assert similarity == 0.0

    def test_zero_magnitude_second_vector_returns_zero(self, matcher):
        """Test zero magnitude second vector returns 0.0."""
        similarity = matcher._calculate_cosine_similarity([1.0, 2.0], [0.0, 0.0])
        assert similarity == 0.0

    def test_mismatched_lengths_uses_shorter_length(self, matcher):
        """Test mismatched vector lengths are handled by using shorter length."""
        vec1 = [1.0, 0.0, 0.0, 0.0, 0.0]  # Length 5
        vec2 = [1.0, 0.0]  # Length 2
        similarity = matcher._calculate_cosine_similarity(vec1, vec2)
        # Should calculate similarity using first 2 elements only
        assert similarity > 0.0  # Vectors align in first 2 dimensions

    def test_negative_values_handled_correctly(self, matcher):
        """Test vectors with negative values compute correctly."""
        vec1 = [1.0, -1.0]
        vec2 = [-1.0, 1.0]
        similarity = matcher._calculate_cosine_similarity(vec1, vec2)
        assert abs(similarity - (-1.0)) < 1e-10  # Perfectly opposite


@pytest.mark.unit
class TestHostFiltering:
    """Test host-based filtering behavior."""

    def test_same_host_documents_included(self, matcher, mock_embedding_provider, url_normalizer):
        """Test documents from same host are included."""
        mock_embedding_provider.return_value = [1.0, 0.0, 0.0]
        query_embedding = [1.0, 0.0, 0.0]

        candidates = [
            Document(
                url=URL("https://example.com/page1"),
                title="Page 1",
                content=Content(markdown="Content", text="Content"),
            ),
            Document(
                url=URL("https://example.com/page2"),
                title="Page 2",
                content=Content(markdown="Content", text="Content"),
            ),
        ]

        matches, confident = matcher.find_similar(
            query_url="https://example.com/query",
            query_embedding=query_embedding,
            candidate_documents=candidates,
            url_normalizer=url_normalizer,
            limit=10,
        )

        assert len(matches) == 2

    def test_different_host_documents_excluded(self, matcher, mock_embedding_provider, url_normalizer):
        """Test documents from different hosts are excluded."""
        mock_embedding_provider.return_value = [1.0, 0.0, 0.0]
        query_embedding = [1.0, 0.0, 0.0]

        candidates = [
            Document(
                url=URL("https://example.com/page1"),
                title="Page 1",
                content=Content(markdown="Content", text="Content"),
            ),
            Document(
                url=URL("https://other.com/page2"),
                title="Page 2",
                content=Content(markdown="Content", text="Content"),
            ),
        ]

        matches, confident = matcher.find_similar(
            query_url="https://example.com/query",
            query_embedding=query_embedding,
            candidate_documents=candidates,
            url_normalizer=url_normalizer,
            limit=10,
        )

        # Only same-host document should be included
        assert len(matches) == 1
        assert matches[0][1].url.value == "https://example.com/page1"


@pytest.mark.unit
class TestThresholdFiltering:
    """Test threshold filtering and ranking."""

    def test_below_threshold_excluded(self, matcher, mock_embedding_provider, url_normalizer):
        """Test documents below similarity threshold are excluded."""
        # Return low similarity embedding
        mock_embedding_provider.return_value = [0.0, 1.0, 0.0]
        query_embedding = [1.0, 0.0, 0.0]  # Orthogonal to returned embedding

        candidates = [
            Document(
                url=URL("https://example.com/page1"),
                title="Page 1",
                content=Content(markdown="Content", text="Content"),
            ),
        ]

        matches, confident = matcher.find_similar(
            query_url="https://example.com/query",
            query_embedding=query_embedding,
            candidate_documents=candidates,
            url_normalizer=url_normalizer,
            limit=10,
        )

        assert len(matches) == 0
        assert not confident

    def test_above_threshold_included(self, matcher, mock_embedding_provider, url_normalizer):
        """Test documents above similarity threshold are included."""
        # Return high similarity embedding
        mock_embedding_provider.return_value = [1.0, 0.0, 0.0]
        query_embedding = [1.0, 0.0, 0.0]  # Identical to returned embedding

        candidates = [
            Document(
                url=URL("https://example.com/page1"),
                title="Page 1",
                content=Content(markdown="Content", text="Content"),
            ),
        ]

        matches, confident = matcher.find_similar(
            query_url="https://example.com/query",
            query_embedding=query_embedding,
            candidate_documents=candidates,
            url_normalizer=url_normalizer,
            limit=10,
        )

        assert len(matches) == 1
        assert confident

    def test_results_sorted_by_similarity_descending(self, matcher, url_normalizer):
        """Test results are sorted by similarity score (highest first)."""

        def variable_embeddings(text):
            # Return different embeddings based on text
            if "high" in text.lower():
                return [1.0, 0.0, 0.0]
            if "medium" in text.lower():
                return [0.9, 0.1, 0.0]
            return [0.8, 0.2, 0.0]

        matcher = SemanticCacheMatcher(
            embedding_provider=variable_embeddings,
            similarity_threshold=0.5,
            return_limit=10,
        )

        query_embedding = [1.0, 0.0, 0.0]
        candidates = [
            Document(url=URL("https://example.com/low"), title="low", content=Content(markdown="Content", text="Content")),
            Document(url=URL("https://example.com/high"), title="high", content=Content(markdown="Content", text="Content")),
            Document(url=URL("https://example.com/medium"), title="medium", content=Content(markdown="Content", text="Content")),
        ]

        matches, _ = matcher.find_similar(
            query_url="https://example.com/query",
            query_embedding=query_embedding,
            candidate_documents=candidates,
            url_normalizer=url_normalizer,
            limit=10,
        )

        # Should be sorted: high, medium, low
        assert matches[0][1].title == "high"
        assert matches[1][1].title == "medium"
        assert matches[2][1].title == "low"
        # Scores should be descending
        assert matches[0][0] >= matches[1][0] >= matches[2][0]


@pytest.mark.unit
class TestLimitParameter:
    """Test limit parameter handling."""

    def test_respects_default_limit(self, matcher, mock_embedding_provider, url_normalizer):
        """Test matcher respects default return_limit."""
        mock_embedding_provider.return_value = [1.0, 0.0, 0.0]
        query_embedding = [1.0, 0.0, 0.0]

        # Create 10 candidates (more than default limit of 5)
        candidates = [
            Document(
                url=URL(f"https://example.com/page{i}"),
                title=f"Page {i}",
                content=Content(markdown="Content", text="Content"),
            )
            for i in range(10)
        ]

        matches, _ = matcher.find_similar(
            query_url="https://example.com/query",
            query_embedding=query_embedding,
            candidate_documents=candidates,
            url_normalizer=url_normalizer,
        )

        # Should return only 5 results (default limit)
        assert len(matches) == 5

    def test_respects_override_limit(self, matcher, mock_embedding_provider, url_normalizer):
        """Test matcher respects override limit parameter."""
        mock_embedding_provider.return_value = [1.0, 0.0, 0.0]
        query_embedding = [1.0, 0.0, 0.0]

        candidates = [
            Document(
                url=URL(f"https://example.com/page{i}"),
                title=f"Page {i}",
                content=Content(markdown="Content", text="Content"),
            )
            for i in range(10)
        ]

        matches, _ = matcher.find_similar(
            query_url="https://example.com/query",
            query_embedding=query_embedding,
            candidate_documents=candidates,
            url_normalizer=url_normalizer,
            limit=3,  # Override default limit
        )

        assert len(matches) == 3


@pytest.mark.unit
class TestLoggingBehavior:
    """Test logging behavior when candidates are rejected."""

    def test_logs_when_top_candidate_below_threshold(self, matcher, mock_embedding_provider, url_normalizer, caplog):
        """Test logging when top candidate is below threshold."""
        caplog.set_level(logging.INFO)

        # Return embedding with low similarity
        mock_embedding_provider.return_value = [0.0, 1.0, 0.0]
        query_embedding = [1.0, 0.0, 0.0]

        candidates = [
            Document(
                url=URL("https://example.com/page1"),
                title="Page 1",
                content=Content(markdown="Content", text="Content"),
            ),
        ]

        matcher.find_similar(
            query_url="https://example.com/query",
            query_embedding=query_embedding,
            candidate_documents=candidates,
            url_normalizer=url_normalizer,
            limit=10,
        )

        # Should log rejection
        assert "Semantic cache candidate rejected" in caplog.text

    def test_no_log_when_candidate_above_threshold(self, matcher, mock_embedding_provider, url_normalizer, caplog):
        """Test no logging when candidate is above threshold."""
        caplog.set_level(logging.INFO)

        # Return embedding with high similarity
        mock_embedding_provider.return_value = [1.0, 0.0, 0.0]
        query_embedding = [1.0, 0.0, 0.0]

        candidates = [
            Document(
                url=URL("https://example.com/page1"),
                title="Page 1",
                content=Content(markdown="Content", text="Content"),
            ),
        ]

        matcher.find_similar(
            query_url="https://example.com/query",
            query_embedding=query_embedding,
            candidate_documents=candidates,
            url_normalizer=url_normalizer,
            limit=10,
        )

        # Should NOT log rejection
        assert "Semantic cache candidate rejected" not in caplog.text

    def test_no_log_when_no_candidates(self, matcher, mock_embedding_provider, url_normalizer, caplog):
        """Test no logging when there are no candidates."""
        caplog.set_level(logging.INFO)

        query_embedding = [1.0, 0.0, 0.0]
        candidates = []

        matcher.find_similar(
            query_url="https://example.com/query",
            query_embedding=query_embedding,
            candidate_documents=candidates,
            url_normalizer=url_normalizer,
            limit=10,
        )

        # Should NOT log when no candidates
        assert "Semantic cache candidate rejected" not in caplog.text
