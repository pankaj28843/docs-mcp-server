"""Keyword extraction and query analysis services.

Pure functions with no external dependencies.
Adapted from sample_keywords.py regex patterns.
"""

import re
from typing import ClassVar

from docs_mcp_server.domain.search import KeywordSet, SearchQuery


class KeywordExtractionService:
    """Extract technical keywords from natural language queries.

    Uses regex patterns inspired by sample_keywords.py.
    Pure, stateless service suitable for unit testing.
    """

    # Stopwords for filtering technical nouns
    STOPWORDS: ClassVar[set[str]] = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "have",
        "will",
        "are",
        "was",
        "were",
        "been",
        "being",
        "you",
        "your",
        "can",
        "should",
        "would",
        "could",
        "may",
        "might",
        "must",
        "than",
        "then",
        "them",
        "they",
        "their",
        "there",
        "where",
        "when",
        "what",
        "which",
        "who",
        "why",
        "how",
        "about",
    }

    # Exclude these common words from acronyms
    ACRONYM_EXCLUDES: ClassVar[set[str]] = {
        "THE",
        "AND",
        "FOR",
        "WITH",
        "HOW",
        "WHAT",
        "WHEN",
        "WHERE",
        "THAT",
        "THIS",
        "FROM",
        "HAVE",
        "WILL",
    }

    def extract(self, query_text: str) -> KeywordSet:
        """Extract all keyword types from query text.

        Args:
            query_text: The raw search query

        Returns:
            KeywordSet with extracted acronyms, nouns, terms, and verbs
        """
        acronyms = self._extract_acronyms(query_text)
        nouns = self._extract_nouns(query_text)
        terms = self._extract_technical_terms(query_text)
        verbs = self._extract_verb_forms(query_text)

        return KeywordSet(
            acronyms=acronyms,
            technical_nouns=nouns,
            technical_terms=terms,
            verb_forms=verbs,
        )

    def _extract_acronyms(self, text: str) -> list[str]:
        """Extract potential acronyms (2-6 uppercase letters).

        Uses regex for efficient extraction and set for deduplication.
        """
        # Match 2-6 uppercase letters, not at start of sentence
        pattern = r"(?<!\. )(?<!\n)\b([A-Z]{2,6})\b"
        matches = re.findall(pattern, text)

        # Filter common words
        return [m for m in matches if m not in self.ACRONYM_EXCLUDES]

    def _extract_nouns(self, text: str) -> list[str]:
        """Extract technical nouns from text.

        Uses lowercase conversion and set-based stopword filtering.
        """
        # Find words (lowercase alphanumeric, 4+ chars)
        words = re.findall(r"\b[a-z][a-z0-9]{2,}\b", text.lower())
        return [w for w in words if w not in self.STOPWORDS and len(w) > 3]

    def _extract_technical_terms(self, text: str) -> list[str]:
        """Extract technical terms (snake_case, CamelCase, hyphenated)."""
        terms: list[str] = []
        # snake_case
        terms.extend(re.findall(r"\b([a-z]+_[a-z_]+)\b", text))
        # CamelCase
        terms.extend(re.findall(r"\b([A-Z][a-z]+[A-Z][a-zA-Z]+)\b", text))
        # hyphenated-terms
        terms.extend(re.findall(r"\b([a-z]+-[a-z-]+)\b", text))
        return terms

    def _extract_verb_forms(self, text: str) -> list[str]:
        """Extract common action verbs and their forms."""
        verb_patterns = [
            r"\b(creat\w+)\b",
            r"\b(updat\w+)\b",
            r"\b(delet\w+)\b",
            r"\b(retriev\w+)\b",
            r"\b(validat\w+)\b",
            r"\b(serializ\w+)\b",
            r"\b(authentica\w+)\b",
            r"\b(authoriz\w+)\b",
            r"\b(configur\w+)\b",
            r"\b(deploy\w+)\b",
            r"\b(instal\w+)\b",
            r"\b(enabl\w+)\b",
            r"\b(disabl\w+)\b",
        ]

        verbs: list[str] = []
        text_lower = text.lower()
        for pattern in verb_patterns:
            verbs.extend(re.findall(pattern, text_lower))
        return verbs


class QueryAnalysisService:
    """Analyze raw queries to produce structured SearchQuery objects."""

    def __init__(self, extractor: KeywordExtractionService):
        """Initialize with a keyword extractor.

        Args:
            extractor: KeywordExtractionService instance for keyword extraction
        """
        self.extractor = extractor

    def analyze(self, raw_query: str, tenant_context: str | None = None) -> SearchQuery:
        """Analyze a raw query string.

        Args:
            raw_query: The user's search query
            tenant_context: Optional tenant name for context-specific processing

        Returns:
            SearchQuery with normalized tokens and extracted keywords
        """
        # Normalize tokens (lowercased, alphanumeric only)
        tokens = [t for t in re.split(r"\W+", raw_query.lower()) if t and t not in self.extractor.STOPWORDS]

        # Extract keywords
        keywords = self.extractor.extract(raw_query)

        return SearchQuery(
            original_text=raw_query,
            normalized_tokens=tokens,
            extracted_keywords=keywords,
            tenant_context=tenant_context,
        )
