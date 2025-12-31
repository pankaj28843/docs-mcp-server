"""Unit tests for domain model.

Following Cosmic Python Chapter 5 (TDD in High/Low Gear):
- Test domain logic in isolation
- Fast tests with no infrastructure
- Clear assertions about business rules
"""

from pydantic import ValidationError
import pytest

from docs_mcp_server.domain import URL, Content, Document, DocumentMetadata


pytestmark = pytest.mark.unit


class TestURL:
    """Test URL value object."""

    def test_creates_valid_url(self):
        """Test creating a valid URL."""
        url = URL(value="https://example.com/doc")
        assert str(url) == "https://example.com/doc"

    def test_creates_http_url(self):
        """Test creating HTTP (not HTTPS) URL."""
        url = URL(value="http://example.com/doc")
        assert str(url) == "http://example.com/doc"

    def test_creates_file_url(self):
        """Test creating file:// URL."""
        url = URL(value="file:///path/to/file.html")
        assert str(url) == "file:///path/to/file.html"

    def test_rejects_empty_url(self):
        """Test that empty URLs are rejected."""
        with pytest.raises(ValidationError):
            URL(value="")

    def test_rejects_invalid_scheme(self):
        """Test that non-HTTP URLs are rejected."""
        with pytest.raises(ValidationError):
            URL(value="ftp://example.com")

    def test_url_is_hashable(self):
        """Test that URLs can be used in sets."""
        url1 = URL(value="https://example.com/doc")
        url2 = URL(value="https://example.com/doc")
        url_set = {url1, url2}
        assert len(url_set) == 1

    def test_url_hash_differs_for_different_urls(self):
        """Test that different URLs have different hashes."""
        url1 = URL(value="https://example.com/doc1")
        url2 = URL(value="https://example.com/doc2")
        assert hash(url1) != hash(url2)

    def test_url_is_immutable(self):
        """Test that URLs are immutable."""
        url = URL(value="https://example.com/doc")
        with pytest.raises(AttributeError):
            url.value = "https://different.com"  # type: ignore

    def test_url_str_method(self):
        """Test URL __str__ returns the value."""
        url = URL(value="https://example.com/page")
        assert str(url) == "https://example.com/page"


class TestContent:
    """Test Content value object."""

    def test_creates_content_with_both_markdown_and_text(self):
        """Test creating content with both fields."""
        content = Content(markdown="# Title", text="Title", excerpt="Excerpt")
        assert content.markdown == "# Title"
        assert content.text == "Title"
        assert not content.is_empty()

    def test_creates_content_with_only_markdown(self):
        """Test content can have just markdown."""
        content = Content(markdown="# Title", text="")
        assert not content.is_empty()

    def test_creates_content_with_only_text(self):
        """Test content can have just text."""
        content = Content(markdown="", text="Some text")
        assert not content.is_empty()

    def test_is_empty_with_whitespace_markdown(self):
        """Test that whitespace-only markdown is considered empty."""
        content = Content(markdown="   \n\t  ", text="Some text")
        assert not content.is_empty()  # Has text

    def test_is_empty_with_whitespace_text(self):
        """Test that whitespace-only text is considered empty."""
        content = Content(markdown="# Title", text="   \n\t  ")
        assert not content.is_empty()  # Has markdown

    def test_rejects_empty_content(self):
        """Test that completely empty content is rejected."""
        with pytest.raises(ValueError, match="Content must have either markdown or text"):
            Content(markdown="", text="")

    def test_rejects_whitespace_only_content(self):
        """Test that whitespace-only content is rejected."""
        with pytest.raises(ValueError, match="Content must have either markdown or text"):
            Content(markdown="   ", text="  \n  ")

    def test_content_is_immutable(self):
        """Test that content is immutable."""
        content = Content(markdown="# Title", text="Text")
        with pytest.raises(AttributeError):
            content.markdown = "Changed"  # type: ignore


class TestDocumentMetadata:
    """Test DocumentMetadata entity."""

    def test_creates_default_metadata(self):
        """Test default metadata creation."""
        meta = DocumentMetadata()
        assert meta.status == "pending"
        assert meta.retry_count == 0
        assert meta.last_fetched_at is None

    def test_mark_success_updates_state(self):
        """Test marking document as successfully fetched."""
        meta = DocumentMetadata(retry_count=3)
        meta.mark_success()
        assert meta.status == "success"
        assert meta.retry_count == 0
        assert meta.last_fetched_at is not None

    def test_mark_failure_increments_retry(self):
        """Test marking document fetch as failed."""
        meta = DocumentMetadata()
        meta.mark_failure()
        assert meta.status == "failed"
        assert meta.retry_count == 1

    def test_validates_retry_count_non_negative(self):
        """Test retry count must be non-negative."""
        with pytest.raises(ValidationError):
            DocumentMetadata(retry_count=-1)

    def test_validates_status_enum(self):
        """Test status must be valid value."""
        with pytest.raises(ValidationError):
            DocumentMetadata(status="invalid")


class TestDocument:
    """Test Document aggregate root."""

    def test_creates_valid_document(self):
        """Test creating a valid document."""
        doc = Document.create(url="https://example.com/doc", title="Test Doc", markdown="# Test", text="Test")
        assert str(doc.url) == "https://example.com/doc"
        assert doc.title == "Test Doc"
        assert not doc.content.is_empty()

    def test_rejects_empty_title(self):
        """Test document must have a title."""
        with pytest.raises(ValidationError):
            Document.create(url="https://example.com/doc", title="", markdown="# Test", text="Test")

    def test_rejects_whitespace_title(self):
        """Test document must have non-whitespace title."""
        url_vo = URL(value="https://example.com/doc")
        content_vo = Content(markdown="# Test", text="Test")
        with pytest.raises(ValueError, match="non-empty title"):
            Document(url=url_vo, title="   \n\t  ", content=content_vo)

    def test_rejects_empty_content(self):
        """Test document must have content."""
        with pytest.raises(ValidationError, match="must have either markdown or text"):
            Document.create(url="https://example.com/doc", title="Test", markdown="", text="")

    def test_documents_equal_by_url(self):
        """Test documents are equal if URLs match (identity)."""
        doc1 = Document.create(url="https://example.com/doc", title="Title 1", markdown="Content 1", text="Text 1")
        doc2 = Document.create(
            url="https://example.com/doc",
            title="Title 2",  # Different title
            markdown="Content 2",  # Different content
            text="Text 2",
        )
        assert doc1 == doc2  # Same URL = same document

    def test_documents_not_equal_to_non_document(self):
        """Test that documents don't equal non-document objects."""
        doc = Document.create(url="https://example.com/doc", title="Title", markdown="Content", text="Text")
        assert doc != "not a document"
        assert doc != 123
        assert doc is not None

    def test_documents_hashable(self):
        """Test documents can be used in sets."""
        doc1 = Document.create(url="https://example.com/doc", title="Title 1", markdown="Content", text="Text")
        doc2 = Document.create(url="https://example.com/doc", title="Title 2", markdown="Different", text="Different")
        doc_set = {doc1, doc2}
        assert len(doc_set) == 1  # Same URL, so only one document

    def test_update_content_changes_content(self):
        """Test updating document content."""
        doc = Document.create(url="https://example.com/doc", title="Title", markdown="Old", text="Old")
        doc.update_content(markdown="New", text="New")
        assert doc.content.markdown == "New"
        assert doc.content.text == "New"
        assert doc.metadata.status == "success"

    def test_mark_fetch_failed_updates_metadata(self):
        """Test marking fetch as failed."""
        doc = Document.create(url="https://example.com/doc", title="Title", markdown="Content", text="Text")
        doc.mark_fetch_failed()
        assert doc.metadata.status == "failed"
        assert doc.metadata.retry_count == 1


class TestDomainInvariants:
    """Test domain invariants and business rules."""

    def test_content_immutability_enforces_value_object_pattern(self):
        """Test that content follows value object pattern."""
        doc = Document.create(url="https://example.com/doc", title="Title", markdown="Original", text="Original")
        original_content = doc.content

        # Update creates NEW content object (value object pattern)
        doc.update_content(markdown="New", text="New")

        # Original content unchanged (immutable)
        assert original_content.markdown == "Original"
        # Document has new content
        assert doc.content.markdown == "New"
        # They're different objects
        assert doc.content is not original_content

    def test_metadata_tracks_state_transitions(self):
        """Test metadata properly tracks document lifecycle."""
        doc = Document.create(url="https://example.com/doc", title="Title", markdown="Content", text="Text")

        # Initial state
        assert doc.metadata.status == "pending"
        assert doc.metadata.retry_count == 0

        # Failed fetch
        doc.mark_fetch_failed()
        assert doc.metadata.status == "failed"
        assert doc.metadata.retry_count == 1

        # Another failure
        doc.mark_fetch_failed()
        assert doc.metadata.retry_count == 2

        # Successful fetch resets retry count
        doc.update_content(markdown="New", text="New")
        assert doc.metadata.status == "success"
        assert doc.metadata.retry_count == 0
