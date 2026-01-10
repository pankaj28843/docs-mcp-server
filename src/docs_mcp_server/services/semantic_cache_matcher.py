"""Semantic cache matcher for finding similar documents.

Deep module for semantic similarity calculation with minimal interface:
- Hides embedding comparison, filtering, and ranking complexity
- Simple interface: find_similar(query_embedding, candidates, threshold)
"""

from collections.abc import Callable
import logging
from urllib.parse import urlparse

from ..domain.model import Document


logger = logging.getLogger(__name__)


class SemanticCacheMatcher:
    """Deep module for semantic similarity matching with minimal interface.

    Hides complexity:
    - Embedding comparison (cosine similarity)
    - Host-based filtering
    - Score-based ranking
    - Threshold application

    Simple interface: find_similar() returns ranked matches above threshold
    """

    def __init__(
        self,
        embedding_provider: Callable[[str], list[float]],
        similarity_threshold: float,
        return_limit: int,
    ):
        """Initialize semantic matcher.

        Args:
            embedding_provider: Function to generate embeddings from text
            similarity_threshold: Minimum similarity score (0.0-1.0)
            return_limit: Maximum number of results to return
        """
        self._embedding_provider = embedding_provider
        self.similarity_threshold = similarity_threshold
        self.return_limit = return_limit

    def find_similar(
        self,
        query_url: str,
        query_embedding: list[float],
        candidate_documents: list[Document],
        url_normalizer: Callable[[str], str],
        limit: int | None = None,
    ) -> tuple[list[tuple[float, Document]], bool]:
        """Find semantically similar documents above threshold.

        Args:
            query_url: Original URL being queried (for host filtering)
            query_embedding: Pre-computed embedding for the query
            candidate_documents: List of candidate documents to compare
            url_normalizer: Function to normalize URLs for embedding
            limit: Optional override for return limit

        Returns:
            Tuple of (ranked_matches, confident) where:
            - ranked_matches: List of (similarity_score, document) tuples
            - confident: True if at least one match exceeds threshold
        """
        request_host = urlparse(query_url).netloc.lower()

        # Calculate similarities for all candidates
        scored: list[tuple[float, Document]] = []
        for document in candidate_documents:
            # Generate candidate embedding
            candidate_payload = f"{document.title} {url_normalizer(str(document.url.value))}"
            candidate_vector = self._embedding_provider(candidate_payload)
            similarity = self._calculate_cosine_similarity(query_embedding, candidate_vector)

            # Filter out different hosts
            candidate_host = urlparse(str(document.url.value)).netloc.lower()
            if request_host and candidate_host and candidate_host != request_host:
                continue

            scored.append((similarity, document))

        # Sort by similarity (highest first)
        scored.sort(key=lambda x: x[0], reverse=True)

        # Apply threshold and limit
        max_results = limit or self.return_limit
        filtered_matches: list[tuple[float, Document]] = []
        confident = False

        for similarity, document in scored:
            if len(filtered_matches) >= max_results:
                break
            if similarity < self.similarity_threshold:
                continue
            confident = True
            filtered_matches.append((similarity, document))

        # Log if top candidate rejected
        if not confident and scored:
            top_similarity, top_document = scored[0]
            logger.info(
                "Semantic cache candidate rejected",
                extra={
                    "requested_url": query_url,
                    "candidate_url": str(top_document.url.value),
                    "score": round(top_similarity, 3),
                    "threshold": self.similarity_threshold,
                },
            )

        return filtered_matches, confident

    def _calculate_cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Calculate cosine similarity between two vectors.

        Args:
            vec1: First embedding vector
            vec2: Second embedding vector

        Returns:
            Similarity score between 0.0 and 1.0
        """
        import math

        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2, strict=True))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)
