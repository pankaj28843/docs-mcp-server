"""Unit tests for Repository pattern.

Following Cosmic Python Chapter 2: Repository Pattern
- Tests repository interface
- Tests fake repository for fast tests
"""

import pytest

from docs_mcp_server.adapters.filesystem_repository import FakeRepository
from docs_mcp_server.domain import Document


class TestFakeRepository:
    """Test in-memory repository (for fast tests)."""

    @pytest.fixture
    def repo(self):
        """Create fresh fake repository for each test."""
        return FakeRepository()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_add_and_get_document(self, repo):
        """Test adding and retrieving a document."""
        doc = Document.create(url="https://example.com/doc1", title="Test Doc", markdown="# Test", text="Test")

        await repo.add(doc)

        retrieved = await repo.get("https://example.com/doc1")
        assert retrieved is not None
        assert retrieved.url.value == doc.url.value
        assert retrieved.title == doc.title

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_nonexistent_document(self, repo):
        """Test getting a document that doesn't exist."""
        result = await repo.get("https://example.com/missing")
        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_documents(self, repo):
        """Test listing all documents."""
        doc1 = Document.create(url="https://example.com/doc1", title="Doc 1", markdown="# Doc 1", text="Doc 1")
        doc2 = Document.create(url="https://example.com/doc2", title="Doc 2", markdown="# Doc 2", text="Doc 2")

        await repo.add(doc1)
        await repo.add(doc2)

        docs = await repo.list()
        assert len(docs) == 2
        urls = {doc.url.value for doc in docs}
        assert "https://example.com/doc1" in urls
        assert "https://example.com/doc2" in urls

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_count_documents(self, repo):
        """Test counting documents."""
        assert await repo.count() == 0

        doc1 = Document.create(url="https://example.com/doc1", title="Doc 1", markdown="# Doc 1", text="Doc 1")
        await repo.add(doc1)
        assert await repo.count() == 1

        doc2 = Document.create(url="https://example.com/doc2", title="Doc 2", markdown="# Doc 2", text="Doc 2")
        await repo.add(doc2)
        assert await repo.count() == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_update_existing_document(self, repo):
        """Test updating an existing document."""
        doc = Document.create(
            url="https://example.com/doc1", title="Original Title", markdown="# Original", text="Original"
        )
        await repo.add(doc)

        # Update the document
        doc.title = "Updated Title"
        doc.update_content(markdown="# Updated", text="Updated")
        await repo.add(doc)

        # Retrieve and verify
        retrieved = await repo.get("https://example.com/doc1")
        assert retrieved.title == "Updated Title"
        assert retrieved.content.markdown == "# Updated"

    @pytest.mark.unit
    def test_clear_repository(self, repo):
        """Test clearing the repository."""
        repo._documents["test"] = Document.create(
            url="https://example.com/test", title="Test", markdown="# Test", text="Test"
        )
        assert len(repo._documents) > 0

        repo.clear()
        assert len(repo._documents) == 0
