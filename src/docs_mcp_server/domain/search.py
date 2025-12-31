"""Domain models for search functionality.

Following Cosmic Python principles:
- Value Objects are immutable (frozen=True)
- Domain logic lives in domain layer
- No infrastructure dependencies

These models support multi-stage search with rich metadata about why results matched.
"""

from pydantic import BaseModel, ConfigDict, Field


class KeywordSet(BaseModel):
    """Value object containing extracted keywords from a query.

    Structured by type to enable targeted search strategies.
    Immutable to ensure query analysis results don't change.
    """

    model_config = ConfigDict(frozen=True)

    acronyms: list[str] = Field(default_factory=list)
    technical_nouns: list[str] = Field(default_factory=list)
    technical_terms: list[str] = Field(default_factory=list)
    verb_forms: list[str] = Field(default_factory=list)


class SearchQuery(BaseModel):
    """Value object representing an analyzed user query.

    Contains original text plus extracted structure to drive search strategies.
    """

    model_config = ConfigDict(frozen=True)

    original_text: str
    normalized_tokens: list[str] = Field(default_factory=list)
    extracted_keywords: KeywordSet = Field(default_factory=KeywordSet)
    tenant_context: str | None = None


class MatchTrace(BaseModel):
    """Value object explaining why a search result was returned.

    Provides transparency for AI agents to understand result quality.
    Critical for debugging and improving search relevance.
    """

    model_config = ConfigDict(frozen=True)

    stage: int
    stage_name: str
    query_variant: str
    match_reason: str
    ripgrep_flags: list[str] = Field(default_factory=list)
    ranking_factors: dict[str, float] = Field(default_factory=dict)


class SearchResult(BaseModel):
    """Value object for a single, enriched search result.

    Combines document reference with metadata explaining the match.
    Immutable to ensure result integrity.
    """

    model_config = ConfigDict(frozen=True)

    document_url: str
    document_title: str
    snippet: str
    match_trace: MatchTrace
    relevance_score: float


class SearchStats(BaseModel):
    """Performance and debug information for a search operation."""

    model_config = ConfigDict(frozen=True)

    stage: int
    files_found: int
    matches_found: int
    files_searched: int
    search_time: float
    warning: str | None = None


class SearchResponse(BaseModel):
    """Value object for a complete search response.

    Includes results and performance statistics.
    """

    model_config = ConfigDict(frozen=True)

    results: list[SearchResult]
    stats: SearchStats | None = None
