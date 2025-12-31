"""Centralized Pydantic models for type-safe MCP tool responses and internal data structures."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


# ============================================================================
# MCP Tool Response Models (Pydantic BaseModel for FastMCP validation)
# ============================================================================


class FetchDocResponse(BaseModel):
    """Response model for fetch_doc MCP tool.

    This model ensures type-safe responses from the fetch_doc MCP tool.
    Supports fetching full document or contextual snippets around specific
    locations (line numbers, fragments).

    Features:
    - Full document retrieval with complete markdown content
    - Surrounding context mode for focused snippet extraction
    - Support for both public URLs and internal file:// URLs
    - URL fragment handling (#section-name or #L123)
    - Graceful error handling with descriptive messages

    Fields:
        url: Canonical document URL (public documentation URL preferred)
        title: Document title extracted from content
        content: Document text content (full markdown or surrounding context)
        context_mode: Context mode used - 'full' or 'surrounding' (includes char count)
        error: Error message if fetch operation failed (None on success)

    Example Success Response:
        {
            "url": "https://docs.python.org/3.13/library/bdb.html",
            "title": "bdb — Debugger framework",
            "content": "# bdb — Debugger framework\\n\\nThe bdb module...",
            "context_mode": "full",
            "error": None
        }

    Example Error Response:
        {
            "url": "https://invalid.example.com/doc.html",
            "title": "",
            "content": "",
            "context_mode": None,
            "error": "Document not found in repository"
        }
    """

    url: str = Field(description="Canonical document URL (public or file://)")
    title: str = Field(description="Document title")
    content: str = Field(description="Document text content (full markdown or surrounding context)")
    context_mode: str | None = Field(
        default=None,
        description="Context mode used: 'full' (entire document) or 'surrounding' (N chars before/after match)",
    )
    error: str | None = Field(default=None, description="Error message if fetch failed")


class SearchResult(BaseModel):
    """Individual search result item with relevance scoring and match transparency.

    Represents a single document in search results with all information
    needed for users to evaluate relevance and navigate to the document.
    Includes match trace metadata explaining WHY the result matched.

    Features:
    - Public documentation URLs with line numbers (#L123)
    - Relevance scoring (0.0-1.0, higher is better)
    - Contextual snippets showing match in surrounding text
    - Human-readable titles
    - Match trace metadata for AI agent transparency

    Fields:
        url: Public documentation URL with optional line number fragment
        title: Human-readable document title
        score: Relevance score (0.0-1.0, based on query match quality)
        snippet: Contextual preview showing query match in surrounding text
        match_stage: Which search stage found this result (1=exact, 2=keyword, 3=relaxed, 4=title-only)
        match_stage_name: Human-readable stage name (e.g., "exact_phrase", "keyword_expansion")
        match_query_variant: The actual query pattern that matched (e.g., "(ruff).*(autofix)")
        match_reason: Explanation of why this result matched
        match_ripgrep_flags: ripgrep flags used for this match (e.g., ["--fixed-strings", "--ignore-case"])

    Example:
        {
            "url": "https://docs.python.org/3.13/library/bdb.html#L380",
            "title": "bdb — Debugger framework",
            "score": 0.95,
            "snippet": "...The Bdb class acts as a generic Python debugger base class...",
            "match_stage": 1,
            "match_stage_name": "exact_phrase",
            "match_query_variant": "debugger framework",
            "match_reason": "Exact phrase match in content",
            "match_ripgrep_flags": ["--fixed-strings", "--ignore-case"]
        }
    """

    url: str = Field(description="Public documentation URL with optional line number (#L123 for precise navigation)")
    title: str = Field(description="Human-readable document title")
    score: float = Field(description="Relevance score (0.0-1.0, higher is better, based on match quality)")
    snippet: str = Field(description="Contextual preview showing match in surrounding text")
    match_stage: int | None = Field(
        default=None, description="Search stage that found this result (1-4, lower is better)"
    )
    match_stage_name: str | None = Field(default=None, description="Human-readable stage name")
    match_query_variant: str | None = Field(default=None, description="Actual query pattern that matched")
    match_reason: str | None = Field(default=None, description="Explanation of why result matched")
    match_ripgrep_flags: list[str] | None = Field(default=None, description="ripgrep flags used for this match")


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
        stats: Optional SearchStats with performance metrics (None unless include_stats=True)
        error: Error message if search operation failed (None on success)
        query: Original query string (included for debugging when error occurs)

    Example Success Response (without stats):
        {
            "results": [
                {
                    "url": "https://docs.python.org/.../page.html#L123",
                    "title": "Page Title",
                    "score": 0.95,
                    "snippet": "...matching content..."
                }
            ],
            "stats": None,
            "error": None,
            "query": None
        }

    Example Success Response (with stats, include_stats=True):
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
        description="Search statistics (included only when include_stats=True parameter is set)",
    )
    error: str | None = Field(default=None, description="Error message if search failed (None on success)")
    query: str | None = Field(default=None, description="Original query (included on error for debugging)")


class BrowseTreeNode(BaseModel):
    """Node in the documentation browse tree.

    Each node represents either a directory or a markdown document and includes
    optional metadata for better discovery.
    """

    name: str = Field(description="Display name of the file or directory")
    path: str = Field(description="Relative path from the tenant storage root")
    type: Literal["file", "directory"] = Field(description="Entry type")
    title: str | None = Field(default=None, description="Human-readable title (from metadata)")
    url: str | None = Field(default=None, description="Public URL if known via metadata")
    has_children: bool | None = Field(
        default=None,
        description="Whether the directory contains visible entries (files/directories)",
    )
    children: list[BrowseTreeNode] | None = Field(
        default=None,
        description="Nested entries revealed when depth allows recursion",
    )


class BrowseTreeResponse(BaseModel):
    """Response model for browsing the tenant's on-disk content hierarchy."""

    root_path: str = Field(description="Requested path relative to the tenant storage root")
    depth: int = Field(description="Depth level that was requested")
    nodes: list[BrowseTreeNode] = Field(
        default_factory=list,
        description="Entries found under the requested path",
    )
    error: str | None = Field(default=None, description="Error message if browsing failed")


BrowseTreeNode.update_forward_refs()


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
