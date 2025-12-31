"""Unit tests for Unit of Work pattern.

Following Cosmic Python Chapter 6: Unit of Work Pattern
- Tests transaction boundaries (commit/rollback)
- Tests context manager protocol
- Tests repository lifecycle
"""

import pytest

from docs_mcp_server.domain.model import Document
from docs_mcp_server.service_layer.filesystem_unit_of_work import FakeUnitOfWork


@pytest.fixture(autouse=True)
def clean_fake_uow():
    """Clear shared state before and after each test."""
    FakeUnitOfWork.clear_shared_store()
    yield
    FakeUnitOfWork.clear_shared_store()


@pytest.mark.unit
class TestFakeUnitOfWork:
    """Test FakeUnitOfWork implementation (in-memory)."""

    @pytest.mark.asyncio
    async def test_can_save_document(self):
        """Test saving document commits to fake repository."""
        doc = Document.create(url="https://example.com/test", title="Test", markdown="# Test", text="Test", excerpt="")

        uow = FakeUnitOfWork()
        async with uow:
            await uow.documents.add(doc)
            await uow.commit()

        # Verify document persisted - create new UoW to check shared store
        uow2 = FakeUnitOfWork()
        async with uow2:
            saved_doc = await uow2.documents.get("https://example.com/test")

        assert saved_doc is not None
        assert saved_doc.url.value == "https://example.com/test"

    @pytest.mark.asyncio
    async def test_rolls_back_uncommitted_work_by_default(self):
        """Test UoW rolls back changes if not explicitly committed."""
        doc = Document.create(url="https://example.com/test2", title="Test", markdown="# Test", text="Test", excerpt="")

        uow = FakeUnitOfWork()
        async with uow:
            await uow.documents.add(doc)
            # No commit()

        # Create NEW UoW to check if document persisted to shared store
        uow2 = FakeUnitOfWork()
        async with uow2:
            saved_doc = await uow2.documents.get("https://example.com/test2")

        # Document should NOT be saved since we didn't commit
        assert saved_doc is None

    async def test_rolls_back_on_error(self):
        """Test UoW rolls back changes if exception raised."""
        doc = Document.create(url="https://example.com/test3", title="Test", markdown="# Test", text="Test", excerpt="")

        uow = FakeUnitOfWork()
        try:
            async with uow:
                await uow.documents.add(doc)
                raise ValueError("Simulated error")
        except ValueError:
            pass

        # Document should NOT be saved due to exception
        saved_doc = await uow.documents.get("https://example.com/test3")
        assert saved_doc is None

    @pytest.mark.asyncio
    async def test_can_retrieve_saved_document(self):
        """Test retrieving document saved in previous UoW context."""
        doc = Document.create(url="https://example.com/test4", title="Test", markdown="# Test", text="Test", excerpt="")

        # First UoW: save document
        uow1 = FakeUnitOfWork()
        async with uow1:
            await uow1.documents.add(doc)
            await uow1.commit()

        # Second UoW: retrieve document (uses same shared store)
        uow2 = FakeUnitOfWork()
        async with uow2:
            saved_doc = await uow2.documents.get("https://example.com/test4")

        assert saved_doc is not None
        assert saved_doc.url.value == "https://example.com/test4"
        assert saved_doc.title == "Test"
