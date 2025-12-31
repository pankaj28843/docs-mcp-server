"""Domain layer - pure business logic with no infrastructure dependencies.

Following Cosmic Python Chapter 2 (Repository Pattern) and Chapter 7 (Aggregates),
this layer contains:
- Entities: Objects with identity (e.g., Document)
- Value Objects: Immutable objects defined by their attributes (e.g., URL, Content)
- Domain logic: Rules that govern the business concepts

Key principles:
1. No dependencies on infrastructure (no HTTP clients, no database drivers)
2. Rich domain model with behavior
3. Type safety with Pydantic
4. Immutability where appropriate (value objects)
"""

from docs_mcp_server.domain.model import URL, Content, Document, DocumentMetadata
from docs_mcp_server.domain.sync_progress import (
    FailureInfo,
    InvalidPhaseTransitionError,
    PhaseChanged,
    SyncCompleted,
    SyncFailed,
    SyncPhase,
    SyncProgress,
    SyncStarted,
    UrlFailed,
    UrlProcessed,
    UrlSkipped,
)


__all__ = [
    "URL",
    "Content",
    "Document",
    "DocumentMetadata",
    "FailureInfo",
    "InvalidPhaseTransitionError",
    "PhaseChanged",
    "SyncCompleted",
    "SyncFailed",
    "SyncPhase",
    "SyncProgress",
    "SyncStarted",
    "UrlFailed",
    "UrlProcessed",
    "UrlSkipped",
]
