"""Adapters layer - Repository implementations.

Following Cosmic Python Chapter 2: Repository Pattern
Abstracts data storage and retrieval using domain model.
"""

from .filesystem_repository import (
    AbstractRepository,
    FakeRepository,
    FileSystemRepository,
)


__all__ = [
    "AbstractRepository",
    "FakeRepository",
    "FileSystemRepository",
]
