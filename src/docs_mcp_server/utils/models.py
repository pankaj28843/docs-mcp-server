"""Centralized Pydantic models for type-safe MCP tool responses and internal data structures."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


# ============================================================================
# MCP Tool Response Models (Pydantic BaseModel for FastMCP validation)
# ============================================================================


class FetchDocResponse(BaseModel):
    """Response model for fetch_doc MCP tool.

    This model ensures type-safe responses from the fetch_doc MCP tool.
    Returns the full document content.

    Features:
    - Full document retrieval with complete markdown content
    - Support for both public URLs and internal file:// URLs
    - Graceful error handling with descriptive messages

    Fields:
        url: Canonical document URL (public documentation URL preferred)
        title: Document title extracted from content
        content: Full document markdown content
        error: Error message if fetch operation failed (None on success)

    Example Success Response:
        {
            "url": "https://docs.python.org/3.13/library/bdb.html",
            "title": "bdb — Debugger framework",
            "content": "# bdb — Debugger framework\\n\\nThe bdb module...",
            "error": None
        }

    Example Error Response:
        {
            "url": "https://invalid.example.com/doc.html",
            "title": "",
            "content": "",
            "error": "Document not found in repository"
        }
    """

    url: str = Field(description="Canonical document URL (public or file://)")
    title: str = Field(description="Document title")
    content: str = Field(description="Full document markdown content")
    error: str | None = Field(default=None, description="Error message if fetch failed")


class SearchResult(BaseModel):
    """Individual search result item.

    Represents a single document in search results with information
    needed for users to navigate to the document.

    Features:
    - Public documentation URLs with line numbers (#L123)
    - Contextual snippets showing match in surrounding text
    - Human-readable titles

    Fields:
        url: Public documentation URL with optional line number fragment
        title: Human-readable document title
        snippet: Contextual preview showing query match in surrounding text

    Example:
        {
            "url": "https://docs.python.org/3.13/library/bdb.html#L380",
            "title": "bdb — Debugger framework",
            "snippet": "...The Bdb class acts as a generic Python debugger base class..."
        }
    """

    url: str = Field(description="Public documentation URL with optional line number (#L123 for precise navigation)")
    title: str = Field(description="Human-readable document title")
    snippet: str = Field(description="Contextual preview showing match in surrounding text")


class SearchDocsResponse(BaseModel):
    """Response model for search_docs MCP tool.

    This model ensures type-safe responses from the search_docs MCP tool.
    Contains search results, optional performance statistics, and error
    handling.

    Features:
    - Scored and ranked search results
    - Optional detailed performance statistics (ripgrep metrics)
    - Graceful error handling with query echo for debugging
    - Empty results list on error (never null)

    Fields:
        results: List of SearchResult objects (empty on error)
        stats: Optional SearchStats with performance metrics (None unless diagnostics are enabled)
        error: Error message if search operation failed (None on success)
        query: Original query string (included for debugging when error occurs)

    Example Success Response (without stats):
        {
            "results": [
                {
                    "url": "https://docs.python.org/.../page.html#L123",
                    "title": "Page Title",
                    "snippet": "...matching content..."
                }
            ],
            "stats": None,
            "error": None,
            "query": None
        }

    Example Success Response (with stats, diagnostics enabled):
        {
            "results": [...],
            "stats": {
                "stage": 2,
                "files_found": 1250,
                "matches": 45,
                "files_searched": 15,
                "search_time": 0.123,
                "timed_out": False,
                "progress": {"stage1_time": 0.05, "stage2_time": 0.073}
            },
            "error": None,
            "query": None
        }

    Example Error Response:
        {
            "results": [],
            "stats": None,
            "error": "Search failed: timeout exceeded",
            "query": "original query text"
        }
    """

    results: list[SearchResult] = Field(
        default_factory=list, description="List of search results (empty on error, never null)"
    )
    stats: SearchStats | None = Field(
        default=None,
        description="Search statistics (included only when infrastructure search_include_stats is true)",
    )
    error: str | None = Field(default=None, description="Error message if search failed (None on success)")
    query: str | None = Field(default=None, description="Original query (included on error for debugging)")

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Exclude None fields (stats, error, query) unless caller overrides."""

        kwargs.setdefault("exclude_none", True)
        return super().model_dump(*args, **kwargs)

    def model_dump_json(self, *args: Any, **kwargs: Any) -> str:
        """Exclude None fields when serializing to JSON by default."""

        kwargs.setdefault("exclude_none", True)
        return super().model_dump_json(*args, **kwargs)


class SearchStats(BaseModel):
    """Detailed search statistics for diagnostics and performance monitoring.

    Comprehensive search performance metrics including multi-stage timing and progress tracking.

    Fields:
        stage: Search stage reached (1=file discovery, 2=context extraction)
        files_found: Total files discovered in stage 1
        matches: Number of final search results after ranking
        files_searched: Files actually searched in stage 2
        search_time: Total search time in seconds
        timed_out: Whether search exceeded timeout limit
        progress: Progress tracking dict with stage-specific metrics
        warning: Warning message if search partially succeeded
        error: Error message if search failed

    Example:
        {
            "stage": 2,
            "files_found": 1250,
            "matches": 45,
            "files_searched": 15,
            "search_time": 0.123,
            "timed_out": False,
            "progress": {"stage1_time": 0.05, "stage2_time": 0.073},
            "warning": None,
            "error": None
        }
    """

    stage: int = Field(description="Search stage reached (1=file discovery, 2=context extraction)")
    files_found: int = Field(description="Total files discovered in stage 1")
    matches: int = Field(description="Number of final search results after ranking")
    files_searched: int = Field(description="Files actually searched in stage 2")
    search_time: float = Field(description="Total search time in seconds")
    timed_out: bool = Field(description="Whether search exceeded timeout limit")
    progress: dict = Field(description="Progress tracking dict with stage-specific metrics")
    warning: str | None = Field(default=None, description="Warning message if search partially succeeded")
    error: str | None = Field(default=None, description="Error message if search failed")


# ============================================================================
# Internal Data Models
# ============================================================================


class ReadabilityContent(BaseModel):
    """Content extracted and processed via article-extractor.

    This model stores the complete content extraction pipeline output.
    Named ReadabilityContent for historical compatibility with the data schema.
    """

    raw_html: str = Field(description="Original HTML content")
    extracted_content: str = Field(description="Extracted content from article-extractor")
    processed_markdown: str = Field(description="html2text processed markdown")
    excerpt: str = Field(description="Brief excerpt from extraction")
    score: float | None = Field(default=None, description="Extraction confidence score")
    success: bool = Field(description="Whether extraction was successful")
    extraction_method: str = Field(description="Method used for extraction")


class SitemapEntry(BaseModel):
    """Entry from a documentation sitemap.

    Represents a single URL from the sitemap with optional last modified date.
    """

    url: HttpUrl = Field(description="Document URL from sitemap")
    lastmod: datetime | None = Field(default=None, description="Last modification timestamp")


class DocPage(BaseModel):
    """Sitemap entry model representing a URL from sitemap.xml.

    This is the internal model for pages stored in cache.
    Includes both discovery metadata and content.
    """

    url: str = Field(description="Source URL of the page")
    title: str = Field(description="Extracted or derived title")
    content: str = Field(description="Cleaned text content (processed markdown)")
    extraction_method: str = Field(default="custom", description="Method used to extract content")
    readability_content: ReadabilityContent | None = Field(
        default=None, description="Complete readability extraction data"
    )
