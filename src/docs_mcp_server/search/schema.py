"""
Schema definition for search indexing.

Defines field types and schema structure for documents, inspired by Whoosh's
schema module. Supports:
- TextField: Analyzed text fields with tokenization, stemming, etc.
- KeywordField: Exact match fields (tags, paths, URLs)
- NumericField: Numeric fields for sorting/filtering
- StoredField: Fields stored but not indexed

Each field can have:
- stored: Whether the raw value is stored in the index
- indexed: Whether the field is searchable
- boost: Field-level boost for scoring (BM25F)
- analyzer: Text analyzer for tokenization
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FieldType(str, Enum):
    """Types of fields supported in the schema."""

    TEXT = "text"
    KEYWORD = "keyword"
    NUMERIC = "numeric"
    STORED = "stored"


@dataclass(frozen=True)
class SchemaField(ABC):
    """Base class for all schema fields."""

    name: str
    stored: bool = True
    indexed: bool = True
    boost: float = 1.0

    @property
    @abstractmethod
    def field_type(self) -> FieldType:
        """Return the field type."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize field definition to dict."""
        return {
            "name": self.name,
            "type": self.field_type.value,
            "stored": self.stored,
            "indexed": self.indexed,
            "boost": self.boost,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SchemaField:
        """Deserialize field definition from dict."""
        field_type = FieldType(data["type"])
        common = {
            "name": data["name"],
            "stored": data.get("stored", True),
            "indexed": data.get("indexed", True),
            "boost": data.get("boost", 1.0),
        }

        if field_type == FieldType.TEXT:
            return TextField(**common, analyzer_name=data.get("analyzer_name"))
        if field_type == FieldType.KEYWORD:
            return KeywordField(**common)
        if field_type == FieldType.NUMERIC:
            return NumericField(**common, sortable=data.get("sortable", True))
        if field_type == FieldType.STORED:
            return StoredField(name=data["name"])
        msg = f"Unknown field type: {field_type}"
        raise ValueError(msg)


@dataclass(frozen=True)
class TextField(SchemaField):
    """
    Analyzed text field for full-text search.

    Text fields are tokenized and analyzed before indexing. Use for:
    - Document body content
    - Titles and headings
    - Any text requiring full-text search

    Args:
        name: Field name (e.g., "body", "title")
        stored: Store raw value for retrieval (default: True)
        indexed: Index for searching (default: True)
        boost: Field weight in scoring (default: 1.0)
        analyzer_name: Name of analyzer to use (default: None = standard)
    """

    analyzer_name: str | None = None

    @property
    def field_type(self) -> FieldType:
        return FieldType.TEXT

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        if self.analyzer_name:
            data["analyzer_name"] = self.analyzer_name
        return data


@dataclass(frozen=True)
class KeywordField(SchemaField):
    """
    Exact-match keyword field.

    Keyword fields are stored as-is without analysis. Use for:
    - File paths and URLs
    - Tags and categories
    - IDs and identifiers
    - Any field requiring exact matching

    Args:
        name: Field name (e.g., "path", "url", "tags")
        stored: Store raw value for retrieval (default: True)
        indexed: Index for searching (default: True)
        boost: Field weight in scoring (default: 1.0)
    """

    @property
    def field_type(self) -> FieldType:
        return FieldType.KEYWORD


@dataclass(frozen=True)
class NumericField(SchemaField):
    """
    Numeric field for sorting and range queries.

    Numeric fields store integer or float values. Use for:
    - Timestamps and dates
    - Scores and rankings
    - Counts and sizes

    Args:
        name: Field name (e.g., "timestamp", "score")
        stored: Store raw value for retrieval (default: True)
        indexed: Index for searching (default: True)
        boost: Field weight in scoring (default: 1.0)
        sortable: Enable sorting on this field (default: True)
    """

    sortable: bool = True

    @property
    def field_type(self) -> FieldType:
        return FieldType.NUMERIC

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["sortable"] = self.sortable
        return data


@dataclass(frozen=True)
class StoredField(SchemaField):
    """
    Stored-only field (not indexed).

    Stored fields are saved with the document but not searchable. Use for:
    - Snippets and excerpts
    - Metadata that doesn't need searching
    - Display-only content

    Args:
        name: Field name (e.g., "excerpt", "raw_html")
    """

    stored: bool = field(default=True, init=False)
    indexed: bool = field(default=False, init=False)
    boost: float = field(default=0.0, init=False)

    @property
    def field_type(self) -> FieldType:
        return FieldType.STORED


@dataclass
class Schema:
    """
    Schema definition for a search index.

    A schema defines the structure of documents in an index, including:
    - Field names and types
    - Analyzers for text fields
    - Boost factors for scoring
    - Storage options

    Example:
        schema = Schema(
            fields=[
                TextField("title", boost=2.0),
                TextField("body", analyzer_name="english"),
                KeywordField("url"),
                KeywordField("tags"),
                NumericField("timestamp"),
            ],
            unique_field="url",
        )
    """

    fields: list[SchemaField]
    unique_field: str = "url"
    name: str = "default"

    def __post_init__(self) -> None:
        """Validate schema after initialization."""
        self._field_map: dict[str, SchemaField] = {f.name: f for f in self.fields}

        # Validate unique field exists
        if self.unique_field not in self._field_map:
            msg = f"Unique field '{self.unique_field}' not found in schema"
            raise ValueError(msg)

    def __getitem__(self, name: str) -> SchemaField:
        """Get field by name."""
        return self._field_map[name]

    def __contains__(self, name: str) -> bool:
        """Check if field exists."""
        return name in self._field_map

    def __iter__(self):
        """Iterate over fields."""
        return iter(self.fields)

    def __len__(self) -> int:
        """Return number of fields."""
        return len(self.fields)

    @property
    def text_fields(self) -> list[TextField]:
        """Return all text fields."""
        return [f for f in self.fields if isinstance(f, TextField)]

    def get_boost(self, field_name: str) -> float:
        """Get boost factor for a field."""
        if field_name in self._field_map:
            return self._field_map[field_name].boost
        return 1.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize schema to dict."""
        return {
            "name": self.name,
            "unique_field": self.unique_field,
            "fields": [f.to_dict() for f in self.fields],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Schema:
        """Deserialize schema from dict."""
        fields = [SchemaField.from_dict(f) for f in data["fields"]]
        return cls(
            fields=fields,
            unique_field=data.get("unique_field", "url"),
            name=data.get("name", "default"),
        )


# Default schema for documentation search
def create_default_schema() -> Schema:
    """
    Create the default schema for documentation search.

    Fields:
    - url: Unique identifier (keyword, boost=1.0) + searchable path segments (text, boost=1.5)
    - title: Document title (text, boost=2.5)
    - headings_h1: H1 headings (text, boost=2.5)
    - headings_h2: H2 headings (text, boost=2.0)
    - headings: All other headings H3+ (text, boost=1.5)
    - body: Main content (text, boost=1.0)
    - path: File path (keyword, boost=1.5)
    - tags: Document tags (keyword, boost=1.5)
    - excerpt: Short description (stored only)
    - language: Document language code (keyword, stored for filtering)
    - timestamp: Last modified time (numeric)
    """
    return Schema(
        name="docs",
        unique_field="url",
        fields=[
            KeywordField("url", boost=1.0),
            TextField("url_path", boost=1.5, analyzer_name="path"),  # Searchable URL path segments
            TextField("title", boost=2.5),
            TextField("headings_h1", boost=2.5),  # H1 headings get same boost as title
            TextField("headings_h2", boost=2.0),  # H2 headings get medium boost
            TextField("headings", boost=1.5),  # H3+ headings get lower boost
            TextField("body", boost=1.0, analyzer_name="english"),
            KeywordField("path", boost=1.5),
            KeywordField("tags", boost=1.5),
            KeywordField("language", boost=0.0, indexed=False),  # Stored for filtering, not searched
            StoredField("excerpt"),
            NumericField("timestamp", sortable=True),
        ],
    )
