"""Search data models."""

from array import array
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Posting:
    """A posting represents a term occurrence in a document."""

    doc_id: str
    frequency: int = 0
    positions: array[int] = None

    def __post_init__(self) -> None:
        if self.positions is None:
            object.__setattr__(self, "positions", array("I"))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "doc_id": self.doc_id,
            "frequency": self.frequency,
            "positions": list(self.positions) if self.positions else [],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Posting":
        """Create from dictionary."""
        positions = array("I", data.get("positions", []))
        return cls(doc_id=data["doc_id"], frequency=data.get("frequency", 0), positions=positions)
