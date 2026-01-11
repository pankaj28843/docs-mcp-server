"""Tests for search models."""
from array import array

import pytest

from docs_mcp_server.search.models import Posting


@pytest.mark.unit
def test_posting_post_init_sets_default_positions():
    """Test __post_init__ sets default positions array."""
    posting = Posting(doc_id="test")
    assert posting.positions is not None
    assert isinstance(posting.positions, array)


@pytest.mark.unit
def test_posting_to_dict():
    """Test to_dict serialization."""
    positions = array("I", [1, 2, 3])
    posting = Posting(doc_id="test", frequency=5, positions=positions)
    result = posting.to_dict()
    assert result == {"doc_id": "test", "frequency": 5, "positions": [1, 2, 3]}


@pytest.mark.unit
def test_posting_from_dict():
    """Test from_dict deserialization."""
    data = {"doc_id": "test", "frequency": 5, "positions": [1, 2, 3]}
    posting = Posting.from_dict(data)
    assert posting.doc_id == "test"
    assert posting.frequency == 5
    assert list(posting.positions) == [1, 2, 3]


@pytest.mark.unit
def test_posting_from_dict_defaults():
    """Test from_dict with missing fields."""
    data = {"doc_id": "test"}
    posting = Posting.from_dict(data)
    assert posting.doc_id == "test"
    assert posting.frequency == 0
    assert list(posting.positions) == []
