"""Additional unit tests for search schema helpers."""

import pytest

from docs_mcp_server.search.schema import FieldType, Schema, SchemaField, TextField


@pytest.mark.unit
def test_schema_field_from_dict_rejects_unknown_type():
    with pytest.raises(ValueError, match="valid FieldType"):
        SchemaField.from_dict({"name": "x", "type": "bad"})


@pytest.mark.unit
def test_schema_getitem_contains_len_iter_and_boost():
    schema = Schema(fields=[TextField("title", boost=2.0)], unique_field="title")

    assert schema["title"].boost == 2.0
    assert "title" in schema
    assert len(list(schema)) == 1
    assert len(schema) == 1
    assert schema.get_boost("missing") == 1.0


@pytest.mark.unit
def test_schema_raises_when_unique_field_missing():
    with pytest.raises(ValueError, match="Unique field"):
        Schema(fields=[TextField("title")], unique_field="url")


@pytest.mark.unit
def test_schema_field_type_enum_roundtrip():
    assert FieldType.TEXT.value == "text"


@pytest.mark.unit
def test_schema_field_from_dict_unknown_branch(monkeypatch):
    class _FakeFieldType:
        TEXT = "text"
        KEYWORD = "keyword"
        __hash__ = object.__hash__
        NUMERIC = "numeric"
        STORED = "stored"

        def __init__(self, value):
            self.value = value

        def __eq__(self, _other):
            return False

    monkeypatch.setattr("docs_mcp_server.search.schema.FieldType", _FakeFieldType)

    with pytest.raises(ValueError, match="Unknown field type"):
        SchemaField.from_dict({"name": "x", "type": "text"})
