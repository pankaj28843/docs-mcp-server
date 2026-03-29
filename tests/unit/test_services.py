"""Unit tests for Service Layer.

Following Cosmic Python Chapter 4: Service Layer Pattern
- Tests use case orchestration
- Tests transaction management via Unit of Work
- Uses FakeUnitOfWork for fast, isolated tests
"""

import pytest

from docs_mcp_server.domain.model import Document
from docs_mcp_server.service_layer import services
from docs_mcp_server.service_layer.filesystem_unit_of_work import FakeUnitOfWork


@pytest.fixture(autouse=True)
def clean_fake_uow():
    """Clear shared state before and after each test."""
    FakeUnitOfWork.clear_shared_store()
    yield
    FakeUnitOfWork.clear_shared_store()


@pytest.mark.unit
class TestStoreDocument:
    """Test store_document service function."""

    @pytest.mark.asyncio
    async def test_creates_new_document(self):
        """Test storing a new document."""
        uow = FakeUnitOfWork()
        result = await services.store_document(
            url="https://example.com/new",
            title="New Doc",
            markdown="# New",
            text="New content",
            excerpt="Excerpt",
            uow=uow,
        )

        # Verify document was created and stored
        assert result is not None
        assert result.url.value == "https://example.com/new"
        assert result.title == "New Doc"
        assert result.metadata.status == "success"

        # Verify it persisted
        uow2 = FakeUnitOfWork()
        async with uow2:
            saved = await uow2.documents.get("https://example.com/new")

        assert saved is not None
        assert saved.title == "New Doc"

    @pytest.mark.asyncio
    async def test_updates_existing_document(self):
        """Test updating an existing document."""
        # Setup: Create initial document
        doc = Document.create(
            url="https://example.com/existing", title="Old Title", markdown="# Old", text="Old content", excerpt=""
        )

        uow1 = FakeUnitOfWork()
        async with uow1:
            await uow1.documents.add(doc)
            await uow1.commit()

        # Act: Update the document
        uow2 = FakeUnitOfWork()
        result = await services.store_document(
            url="https://example.com/existing",
            title="New Title",
            markdown="# New",
            text="New content",
            excerpt="New excerpt",
            uow=uow2,
        )

        # Assert: Verify update
        assert result.title == "New Title"
        assert result.content.markdown == "# New"
        assert result.content.text == "New content"
        assert result.metadata.status == "success"

    @pytest.mark.asyncio
    async def test_marks_document_as_success(self):
        """Test that storing marks document as successfully fetched."""
        uow = FakeUnitOfWork()
        result = await services.store_document(
            url="https://example.com/doc", title="Doc", markdown="# Doc", text="Doc", excerpt="", uow=uow
        )

        assert result.metadata.status == "success"
        assert result.metadata.last_fetched_at is not None
        assert result.metadata.retry_count == 0

    @pytest.mark.asyncio
    async def test_missing_excerpt_defaults_to_empty_string(self):
        """Store guardrail: excerpt None should degrade gracefully for downstream tools."""
        uow = FakeUnitOfWork()
        stored = await services.store_document(
            url="https://example.com/guardrail",
            title="Guardrail",
            markdown="# Content",
            text="Content",
            excerpt=None,
            uow=uow,
        )

        assert stored.content.excerpt == ""
        # Ensure the persisted copy also keeps the normalized excerpt
        uow2 = FakeUnitOfWork()
        async with uow2:
            persisted = await uow2.documents.get("https://example.com/guardrail")
        assert persisted is not None
        assert persisted.content.excerpt == ""


@pytest.mark.unit
class TestMarkDocumentFailed:
    """Test mark_document_failed service function."""

    @pytest.mark.asyncio
    async def test_increments_retry_count(self):
        """Test marking document as failed increments retry count."""
        # Setup: Create document
        doc = Document.create(url="https://example.com/doc", title="Doc", markdown="# Doc", text="Doc", excerpt="")

        uow1 = FakeUnitOfWork()
        async with uow1:
            await uow1.documents.add(doc)
            await uow1.commit()

        # Act: Mark as failed
        uow2 = FakeUnitOfWork()
        await services.mark_document_failed("https://example.com/doc", uow2)

        # Assert: Verify retry count increased
        uow3 = FakeUnitOfWork()
        async with uow3:
            updated = await uow3.documents.get("https://example.com/doc")

        assert updated is not None
        assert updated.metadata.retry_count == 1
        assert updated.metadata.status == "failed"

    @pytest.mark.asyncio
    async def test_handles_missing_document(self):
        """Test marking non-existent document as failed doesn't error."""
        uow = FakeUnitOfWork()
        # Should not raise exception
        await services.mark_document_failed("https://example.com/missing", uow)
