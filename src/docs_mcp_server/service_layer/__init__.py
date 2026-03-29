"""Service layer - Business logic orchestration.

Following Cosmic Python Chapter 4, 5, 6:
- Service layer orchestrates use cases
- Uses Unit of Work for transaction management
- Works with domain model and repositories
"""

from .filesystem_unit_of_work import (
    AbstractUnitOfWork,
    FakeUnitOfWork,
    FileSystemUnitOfWork,
)
from .services import (
    store_document,
)


__all__ = [
    "AbstractUnitOfWork",
    "FakeUnitOfWork",
    "FileSystemUnitOfWork",
    "store_document",
]
