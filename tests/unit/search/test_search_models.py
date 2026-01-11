"""Test search models functionality."""

from array import array

from docs_mcp_server.search.models import Posting


class TestPosting:
    """Test Posting model."""

    def test_create_posting(self):
        """Test creating a Posting."""
        positions = array("I", [0, 10, 20])
        posting = Posting(doc_id="doc1", frequency=5, positions=positions)

        assert posting.doc_id == "doc1"
        assert posting.frequency == 5
        assert list(posting.positions) == [0, 10, 20]

    def test_create_posting_with_defaults(self):
        """Test creating a Posting with default values."""
        posting = Posting(doc_id="doc1")

        assert posting.doc_id == "doc1"
        assert posting.frequency == 0
        assert list(posting.positions) == []

    def test_create_posting_with_none_positions(self):
        """Test creating a Posting with None positions (triggers __post_init__)."""
        posting = Posting(doc_id="doc1", frequency=2, positions=None)

        assert posting.doc_id == "doc1"
        assert posting.frequency == 2
        assert list(posting.positions) == []

    def test_posting_from_dict_with_defaults(self):
        """Test creating Posting from dictionary with default values."""
        data = {"doc_id": "doc2"}
        posting = Posting.from_dict(data)
        
        assert posting.doc_id == "doc2"
        assert posting.frequency == 0
        assert list(posting.positions) == []

    def test_posting_from_dict_with_empty_positions(self):
        """Test creating Posting from dictionary with empty positions."""
        data = {"doc_id": "doc3", "frequency": 2, "positions": []}
        posting = Posting.from_dict(data)
        
        assert posting.doc_id == "doc3"
        assert posting.frequency == 2
        assert list(posting.positions) == []

    def test_posting_to_dict_with_none_positions_edge_case(self):
        """Test to_dict when positions is somehow None (edge case)."""
        # Create posting and manually set positions to None to test the edge case
        posting = Posting(doc_id="doc4", frequency=1)
        object.__setattr__(posting, "positions", None)
        
        result = posting.to_dict()
        assert result == {"doc_id": "doc4", "frequency": 1, "positions": []}  # Should be empty array, not None

    def test_posting_equality(self):
        """Test Posting equality."""
        positions1 = array("I", [0, 10, 20])
        positions2 = array("I", [0, 10, 20])
        positions3 = array("I", [1, 11, 21])

        posting1 = Posting(doc_id="doc1", frequency=5, positions=positions1)
        posting2 = Posting(doc_id="doc1", frequency=5, positions=positions2)
        posting3 = Posting(doc_id="doc2", frequency=5, positions=positions3)

        assert posting1 == posting2
        assert posting1 != posting3

    def test_posting_repr(self):
        """Test Posting string representation."""
        positions = array("I", [1, 5, 9])
        posting = Posting(doc_id="doc1", frequency=3, positions=positions)
        repr_str = repr(posting)

        assert "doc1" in repr_str
        assert "3" in repr_str

    def test_posting_to_dict(self):
        """Test converting Posting to dictionary."""
        positions = array("I", [0, 5, 10])
        posting = Posting(doc_id="doc1", frequency=3, positions=positions)

        result = posting.to_dict()

        assert result == {"doc_id": "doc1", "frequency": 3, "positions": [0, 5, 10]}

    def test_posting_to_dict_empty_positions(self):
        """Test converting Posting with empty positions to dictionary."""
        posting = Posting(doc_id="doc1", frequency=1)

        result = posting.to_dict()

        assert result == {"doc_id": "doc1", "frequency": 1, "positions": []}

    def test_posting_to_dict_none_positions(self):
        """Test converting Posting with None positions to dictionary."""
        # Create posting with None positions to test the conditional
        posting = Posting(doc_id="doc1", frequency=1, positions=None)

        result = posting.to_dict()

        assert result == {"doc_id": "doc1", "frequency": 1, "positions": []}

    def test_posting_from_dict(self):
        """Test creating Posting from dictionary."""
        data = {"doc_id": "doc1", "frequency": 3, "positions": [0, 5, 10]}

        posting = Posting.from_dict(data)

        assert posting.doc_id == "doc1"
        assert posting.frequency == 3
        assert list(posting.positions) == [0, 5, 10]

    def test_posting_from_dict_minimal(self):
        """Test creating Posting from minimal dictionary."""
        data = {"doc_id": "doc1"}

        posting = Posting.from_dict(data)

        assert posting.doc_id == "doc1"
        assert posting.frequency == 0
        assert list(posting.positions) == []

    def test_posting_roundtrip_serialization(self):
        """Test that to_dict and from_dict are inverses."""
        positions = array("I", [1, 3, 7, 15])
        original = Posting(doc_id="test_doc", frequency=4, positions=positions)

        # Convert to dict and back
        data = original.to_dict()
        restored = Posting.from_dict(data)

        assert restored.doc_id == original.doc_id
        assert restored.frequency == original.frequency
        assert list(restored.positions) == list(original.positions)
