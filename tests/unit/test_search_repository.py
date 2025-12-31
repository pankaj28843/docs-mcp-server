"""Unit tests for search repository implementations."""

import pytest

from docs_mcp_server.adapters.search_repository import AbstractSearchRepository


@pytest.mark.unit
class TestAbstractSearchRepository:
    """Test AbstractSearchRepository interface."""

    def test_is_abstract_class(self):
        """Test AbstractSearchRepository cannot be instantiated."""
        with pytest.raises(TypeError):
            AbstractSearchRepository()  # type: ignore

    def test_defines_search_documents_interface(self):
        """Test AbstractSearchRepository defines search_documents method."""
        assert hasattr(AbstractSearchRepository, "search_documents")
        assert callable(AbstractSearchRepository.search_documents)
