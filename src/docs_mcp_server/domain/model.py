"""Domain model - entities and value objects.

Following Cosmic Python principles + modern Python best practices:
- Domain model has NO dependencies on infrastructure
- Entities have identity and can change over time
- Value Objects are immutable and defined by their attributes
- All domain logic lives here
- Uses Pydantic dataclasses for validation (FastMCP/Starlette pattern)

Why Pydantic dataclasses?
- Automatic validation at construction (defensive programming)
- Immutable value objects with frozen=True
- Compatible with modern frameworks (FastMCP, Starlette, FastAPI)
- Still pure domain model - no infrastructure dependencies
- Type safety and runtime validation
"""

from datetime import datetime, timezone
from typing import Self

from pydantic import Field
from pydantic.dataclasses import dataclass


# Value Objects (immutable)
@dataclass(frozen=True)
class URL:
    """Value object representing a URL.

    Immutable - follows value object pattern from Cosmic Python Ch 7.
    Uses Pydantic for validation.
    Supports http://, https://, and file:// schemes.
    """

    value: str = Field(min_length=1, pattern=r"^(https?|file)://")

    def __str__(self) -> str:
        return self.value

    def __hash__(self) -> int:
        return hash(self.value)


@dataclass(frozen=True)
class Content:
    """Value object representing document content.

    Contains both markdown and structured text representation.
    Validates that at least one of markdown or text has non-whitespace content.
    """

    markdown: str = ""
    text: str = ""
    excerpt: str = ""

    def __post_init__(self) -> None:
        """Validate content invariants after Pydantic validation."""
        if not self.markdown.strip() and not self.text.strip():
            raise ValueError("Content must have either markdown or text")

    def is_empty(self) -> bool:
        """Check if content is effectively empty."""
        return not self.markdown.strip() and not self.text.strip()


# Entities (have identity, can be mutable)
@dataclass
class DocumentMetadata:
    """Metadata about a document's processing state.

    Tracks fetching, retry logic, and storage paths.

    Storage:
    - markdown_rel_path: Nested path like "docs.djangoproject.com/en/5.1/intro/tutorial01.md"
    - document_key: SHA-256 hash of canonical URL (for backward compatibility)

    Mutable because it tracks state changes.
    """

    # Storage paths
    markdown_rel_path: str | None = None  # Nested path from PathBuilder
    document_key: str | None = None  # SHA-256 hash of canonical URL

    # State tracking
    indexed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_fetched_at: datetime | None = None
    next_due_at: datetime | None = None
    retry_count: int = Field(default=0, ge=0)
    status: str = Field(default="pending", pattern="^(pending|success|failed)$")

    def mark_success(self) -> None:
        """Mark document as successfully fetched."""
        object.__setattr__(self, "last_fetched_at", datetime.now(timezone.utc))
        object.__setattr__(self, "status", "success")
        object.__setattr__(self, "retry_count", 0)

    def mark_failure(self) -> None:
        """Mark document fetch as failed."""
        object.__setattr__(self, "retry_count", self.retry_count + 1)
        object.__setattr__(self, "status", "failed")


@dataclass
class Document:
    """Aggregate root for document entity.

    Following Cosmic Python Ch 7 (Aggregates):
    - This is the main entity with identity (URL)
    - Contains value objects (Content)
    - Enforces invariants and business rules

    Mutable because documents can be updated (new content, metadata changes).
    """

    url: URL
    title: str  # No Field() needed - Pydantic validates min_length via annotation
    content: Content
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    snippet: str | None = None  # For search results

    def __post_init__(self) -> None:
        """Validate document invariants after Pydantic validation.

        Allows empty content for documents pending fetch (discovered but not yet processed).
        """
        if not self.title.strip():
            raise ValueError("Document must have a non-empty title")

    def __eq__(self, other: object) -> bool:
        """Documents are equal if they have the same URL (identity)."""
        if not isinstance(other, Document):
            return False
        return self.url == other.url

    def __hash__(self) -> int:
        """Hash based on URL (identity)."""
        return hash(self.url)

    @classmethod
    def create(
        cls,
        url: str,
        title: str,
        markdown: str,
        text: str,
        excerpt: str = "",
    ) -> Self:
        """Factory method to create a document from primitives.

        This is the recommended way to create documents from external data.
        Pydantic will validate all fields automatically.
        """
        url_vo = URL(value=url)
        content_vo = Content(markdown=markdown, text=text, excerpt=excerpt)
        return cls(url=url_vo, title=title, content=content_vo)

    def update_content(self, markdown: str, text: str, excerpt: str = "") -> None:
        """Update document content (creates new Content value object)."""
        # Since Content is frozen (immutable), we create a new one
        new_content = Content(markdown=markdown, text=text, excerpt=excerpt)
        object.__setattr__(self, "content", new_content)
        self.metadata.mark_success()

    def mark_fetch_failed(self) -> None:
        """Mark that fetching this document failed."""
        self.metadata.mark_failure()
