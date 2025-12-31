"""Unit tests for the lightweight search storage module."""

from __future__ import annotations

import json

import pytest

from docs_mcp_server.search.schema import KeywordField, Schema, StoredField, TextField
from docs_mcp_server.search.storage import (
    MAX_STORED_BODY_CHARS,
    MAX_STORED_TITLE_CHARS,
    IndexSegment,
    JsonSegmentStore,
    SegmentWriter,
    StorageError,
)


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_segment_store_limits() -> None:
    JsonSegmentStore.set_max_segments(None)
    yield
    JsonSegmentStore.set_max_segments(None)


def _build_schema() -> Schema:
    return Schema(
        fields=[
            KeywordField("url"),
            TextField("title", analyzer_name="english-nostem", boost=3.0),
            KeywordField("tags"),
            StoredField("excerpt"),
        ],
        unique_field="url",
        name="test",
    )


def test_segment_writer_indexes_text_and_keyword_fields() -> None:
    schema = _build_schema()
    writer = SegmentWriter(schema)

    writer.add_document(
        {
            "url": "https://example.com/docs",
            "title": "Hello World Search",
            "tags": ["search", "docs"],
            "excerpt": "Greeting",
        }
    )

    segment = writer.build()

    assert segment.doc_count == 1

    stored = segment.get_document("https://example.com/docs")
    assert stored is not None
    assert stored["title"] == "Hello World Search"
    assert stored["excerpt"] == "Greeting"

    # Access postings directly (as BM25 engine does)
    title_postings = segment.postings.get("title", {}).get("hello", [])
    assert len(title_postings) == 1
    assert title_postings[0].frequency == 1
    assert segment.field_lengths["title"]["https://example.com/docs"] == 3

    tag_postings = segment.postings.get("tags", {}).get("search", [])
    assert len(tag_postings) == 1
    assert tag_postings[0].frequency == 1


def test_segment_writer_rejects_duplicate_unique_field() -> None:
    schema = _build_schema()
    writer = SegmentWriter(schema)

    writer.add_document({"url": "https://example.com", "title": "Doc"})

    with pytest.raises(StorageError):
        writer.add_document({"url": "https://example.com", "title": "Duplicate"})


def test_index_segment_serialization_round_trip() -> None:
    schema = _build_schema()
    writer = SegmentWriter(schema, segment_id="segment-1")
    writer.add_document({"url": "https://example.com", "title": "Round Trip"})

    segment = writer.build()
    payload = segment.to_dict()
    restored = IndexSegment.from_dict(payload)

    assert restored.segment_id == "segment-1"
    assert restored.doc_count == 1
    # Access postings directly
    assert restored.postings.get("title", {}).get("round", [])[0].frequency == 1


def test_json_segment_store_round_trip(tmp_path) -> None:
    schema = _build_schema()
    writer = SegmentWriter(schema, segment_id="segment-1")
    writer.add_document({"url": "https://example.com", "title": "Round Trip"})
    segment = writer.build()

    store = JsonSegmentStore(tmp_path / "segments")
    saved_path = store.save(segment)

    assert saved_path.exists()
    assert saved_path.suffix == ".json"
    latest = store.latest()
    assert latest is not None
    assert latest.segment_id == "segment-1"
    # Verify manifest contains the segment
    manifest = json.loads((store.directory / JsonSegmentStore.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["segments"][-1]["segment_id"] == "segment-1"
    assert manifest["segments"][-1]["files"] == ["segment-1.json"]


def test_json_segment_store_tracks_manifest_timestamp(tmp_path) -> None:
    schema = _build_schema()
    writer = SegmentWriter(schema, segment_id="segment-1")
    writer.add_document({"url": "https://example.com", "title": "Timestamp"})
    segment = writer.build()

    store = JsonSegmentStore(tmp_path / "segments")
    store.save(segment)

    manifest = json.loads((store.directory / JsonSegmentStore.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert "updated_at" in manifest
    assert manifest["updated_at"].startswith("20")


def test_json_segment_store_records_related_files(tmp_path) -> None:
    schema = _build_schema()
    writer = SegmentWriter(schema, segment_id="segment-1")
    writer.add_document({"url": "https://example.com", "title": "Related"})
    segment = writer.build()

    store = JsonSegmentStore(tmp_path / "segments")
    auxiliary = store.directory / "segment-1.meta.json"
    auxiliary.write_text("{}", encoding="utf-8")

    store.save(segment, related_files=[auxiliary])

    manifest = json.loads((store.directory / JsonSegmentStore.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["segments"][-1]["files"] == ["segment-1.json", "segment-1.meta.json"]


def test_json_segment_store_load_specific_segment(tmp_path) -> None:
    schema = _build_schema()
    writer_one = SegmentWriter(schema, segment_id="segment-1")
    writer_one.add_document({"url": "https://example.com/one", "title": "One"})
    segment_one = writer_one.build()

    writer_two = SegmentWriter(schema, segment_id="segment-2")
    writer_two.add_document({"url": "https://example.com/two", "title": "Two"})
    segment_two = writer_two.build()

    store = JsonSegmentStore(tmp_path / "segments")
    store.save(segment_one)
    store.save(segment_two)

    loaded = store.load("segment-1")
    assert loaded is not None
    assert loaded.segment_id == "segment-1"

    latest = store.latest()
    assert latest is not None
    assert latest.segment_id == "segment-2"

    manifest = json.loads((store.directory / JsonSegmentStore.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert [entry["segment_id"] for entry in manifest["segments"]] == ["segment-1", "segment-2"]


def test_json_segment_store_reuses_existing_segments(tmp_path) -> None:
    schema = _build_schema()
    writer = SegmentWriter(schema, segment_id="segment-stable")
    writer.add_document({"url": "https://example.com/one", "title": "One"})
    segment = writer.build()

    store = JsonSegmentStore(tmp_path / "segments")
    store.save(segment)
    first_manifest = json.loads((store.directory / JsonSegmentStore.MANIFEST_FILENAME).read_text(encoding="utf-8"))

    # Saving identical segment should not duplicate manifest entries
    store.save(segment)
    second_manifest = json.loads((store.directory / JsonSegmentStore.MANIFEST_FILENAME).read_text(encoding="utf-8"))

    assert first_manifest["segments"] == second_manifest["segments"]
    assert len(second_manifest["segments"]) == 1
    assert second_manifest["segments"][0]["segment_id"] == "segment-stable"


def test_json_segment_store_prunes_old_segments(tmp_path) -> None:
    schema = _build_schema()
    store = JsonSegmentStore(tmp_path / "segments")
    JsonSegmentStore.set_max_segments(1)

    for idx in range(3):
        writer = SegmentWriter(schema, segment_id=f"segment-{idx}")
        writer.add_document({"url": f"https://example.com/{idx}", "title": f"Doc {idx}"})
        store.save(writer.build())

    manifest = json.loads((store.directory / JsonSegmentStore.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    # Only the latest segment remains on disk/manifest
    assert len(manifest["segments"]) == 1
    assert manifest["segments"][0]["segment_id"] == "segment-2"

    stored_files = list((tmp_path / "segments").glob("segment-*.json"))
    assert len(stored_files) == 1


def test_json_segment_store_prune_to_segment_ids(tmp_path) -> None:
    schema = _build_schema()
    store = JsonSegmentStore(tmp_path / "segments")

    writer_one = SegmentWriter(schema, segment_id="segment-1")
    writer_one.add_document({"url": "https://example.com/one", "title": "One"})
    store.save(writer_one.build())

    writer_two = SegmentWriter(schema, segment_id="segment-2")
    writer_two.add_document({"url": "https://example.com/two", "title": "Two"})
    store.save(writer_two.build())

    store.prune_to_segment_ids(["segment-2"])

    manifest = json.loads((store.directory / JsonSegmentStore.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert len(manifest["segments"]) == 1
    assert manifest["segments"][0]["segment_id"] == "segment-2"
    assert not (store.directory / "segment-1.json").exists()


def test_segment_writer_truncates_and_filters_stored_fields() -> None:
    schema = Schema(
        fields=[
            KeywordField("url"),
            TextField("title"),
            TextField("body"),
            KeywordField("path"),
            KeywordField("tags"),
            KeywordField("language"),
        ],
        unique_field="url",
        name="trim-test",
    )
    writer = SegmentWriter(schema)
    long_title = "T" * (MAX_STORED_TITLE_CHARS + 50)
    long_body = "B" * (MAX_STORED_BODY_CHARS + 123)

    writer.add_document(
        {
            "url": "https://example.com/doc",
            "title": long_title,
            "body": long_body,
            "path": "/docs/example",
            "tags": ["keep", "drop"],
            "language": "en",
        }
    )

    segment = writer.build()
    stored = segment.get_document("https://example.com/doc")
    assert stored is not None
    assert stored["language"] == "en"
    assert stored["path"] == "/docs/example"
    assert len(stored["body"]) == MAX_STORED_BODY_CHARS
    assert len(stored["title"]) == MAX_STORED_TITLE_CHARS
    assert "tags" not in stored


def test_json_segment_store_loads_manual_json_payloads(tmp_path) -> None:
    store = JsonSegmentStore(tmp_path / "segments")
    payload = {
        "schema": _build_schema().to_dict(),
        "postings": {},
        "stored_fields": {},
        "field_lengths": {},
        "segment_id": "legacy",
    }
    legacy_path = store.directory / "legacy.json"
    legacy_path.write_text(json.dumps(payload), encoding="utf-8")

    # Use segment_path() instead of segment_exists()
    assert store.segment_path("legacy") is not None
    loaded = store.load("legacy")
    assert loaded is not None
    assert loaded.segment_id == "legacy"
