"""Lightweight postings storage for the docs search stack.

The storage module keeps the first iteration of the search overhaul focused on
in-memory data structures that are easy to exercise in unit tests. The module
provides:

* ``SegmentWriter`` - accepts schema-aware documents and produces immutable
  ``IndexSegment`` instances with postings and field length metadata.
* ``IndexSegment`` - exposes helpers for retrieving postings, stored fields, and
  serialization for persistence to JSON.
* ``JsonSegmentStore`` - persists segments as minified JSON with content-addressable
  fingerprints for deduplication.

The API intentionally mirrors concepts from Whoosh so later phases (JSONL/SQLite
persistency) can reuse the same interfaces.
"""

from __future__ import annotations

from array import array
from collections import defaultdict
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from docs_mcp_server.search.analyzers import KeywordAnalyzer, Token, get_analyzer
from docs_mcp_server.search.schema import KeywordField, NumericField, Schema, SchemaField, TextField


try:  # pragma: no cover - optional speedup dependency
    import orjson as _orjson
except Exception:  # pragma: no cover - gracefully fall back to stdlib json
    _orjson = None


logger = logging.getLogger(__name__)

_JSON_SEPARATORS = (",", ":")

MAX_STORED_BODY_CHARS = 4096
MAX_STORED_EXCERPT_CHARS = 640
MAX_STORED_TITLE_CHARS = 512
_STORED_FIELD_ALLOWLIST = {
    "url",
    "title",
    "body",
    "path",
    "excerpt",
    "language",
}
_STORED_FIELD_LIMITS = {
    "body": MAX_STORED_BODY_CHARS,
    "excerpt": MAX_STORED_EXCERPT_CHARS,
    "title": MAX_STORED_TITLE_CHARS,
    "path": 512,
    "url": 2048,
}


def _load_json_payload(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if _orjson is not None:
        return cast("dict[str, Any]", _orjson.loads(data))
    return cast("dict[str, Any]", json.loads(data.decode("utf-8")))


def _serialize_json_payload(payload: Any) -> bytes:
    if _orjson is not None:
        return _orjson.dumps(payload)
    return json.dumps(payload, ensure_ascii=False, separators=_JSON_SEPARATORS).encode("utf-8")


def _normalize_stored_value(field_name: str, value: Any) -> Any | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    limit = _STORED_FIELD_LIMITS.get(field_name)
    if limit is not None and len(value) > limit:
        return value[:limit]
    return value


class StorageError(ValueError):
    """Raised when invalid documents or operations are encountered."""


@dataclass(frozen=True, slots=True)
class Posting:
    """Represents a postings entry for a term within a field.

    Minimal structure: only doc_id and positions are stored.
    Frequency is derived from len(positions) to save space.
    """

    doc_id: str
    positions: array

    @property
    def frequency(self) -> int:
        """Derive frequency from positions length."""
        return len(self.positions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "d": self.doc_id,
            "p": list(self.positions),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Posting:
        # Support both minimal keys and legacy keys
        doc_id = data.get("d") or data.get("doc_id", "")
        positions = data.get("p") or data.get("positions", [])
        return cls(
            doc_id=str(doc_id),
            positions=array("I", (int(pos) for pos in positions)),
        )


@dataclass(frozen=True, slots=True)
class IndexSegment:
    """Immutable representation of a search segment.

    Minimal footprint: field_lengths is derived from postings on load,
    and serialization uses short keys to reduce disk usage.
    """

    schema: Schema
    postings: dict[str, dict[str, list[Posting]]]
    stored_fields: dict[str, dict[str, Any]]
    field_lengths: dict[str, dict[str, int]]
    segment_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def doc_count(self) -> int:
        return len(self.stored_fields)

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        return self.stored_fields.get(doc_id)

    def get_postings(self, field_name: str, term: str) -> list[Posting]:
        """Return postings for a specific term in a field."""
        field_postings = self.postings.get(field_name, {})
        return field_postings.get(term, [])

    def to_dict(self) -> dict[str, Any]:
        """Serialize with minimal keys: s=schema, p=postings, d=docs, i=id, c=created."""
        return {
            "s": self.schema.to_dict(),
            "p": {
                field: {term: [posting.to_dict() for posting in postings] for term, postings in terms.items()}
                for field, terms in self.postings.items()
            },
            "d": self.stored_fields,
            "i": self.segment_id,
            "c": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> IndexSegment:
        # Support both minimal keys and legacy keys
        schema_data = data.get("s") or data.get("schema", {})
        schema = Schema.from_dict(schema_data)

        raw_postings = data.get("p") or data.get("postings", {})
        postings: dict[str, dict[str, list[Posting]]] = {}
        for field_name, terms in raw_postings.items():
            postings[field_name] = {}
            for term, entries in terms.items():
                postings[field_name][term] = [Posting.from_dict(entry) for entry in entries]

        raw_stored = data.get("d") or data.get("stored_fields", {})
        stored_fields = {k: dict(v) for k, v in raw_stored.items()}

        # Derive field_lengths from postings if not present (minimal format)
        raw_lengths = data.get("field_lengths", {})
        field_lengths = {k: dict(v) for k, v in raw_lengths.items()} if raw_lengths else _derive_field_lengths(postings)

        created_raw = data.get("c") or data.get("created_at")
        created = datetime.fromisoformat(created_raw) if isinstance(created_raw, str) else datetime.now(timezone.utc)

        segment_id = data.get("i") or data.get("segment_id") or uuid4().hex

        return cls(
            schema=schema,
            postings=postings,
            stored_fields=stored_fields,
            field_lengths=field_lengths,
            segment_id=str(segment_id),
            created_at=created,
        )


def _derive_field_lengths(postings: dict[str, dict[str, list[Posting]]]) -> dict[str, dict[str, int]]:
    """Reconstruct field_lengths from postings by summing position counts per doc."""
    field_lengths: dict[str, dict[str, int]] = {}
    for field_name, terms in postings.items():
        doc_lengths: dict[str, int] = {}
        for posting_list in terms.values():
            for posting in posting_list:
                doc_lengths[posting.doc_id] = doc_lengths.get(posting.doc_id, 0) + posting.frequency
        if doc_lengths:
            field_lengths[field_name] = doc_lengths
    return field_lengths


class SegmentWriter:
    """Builds index segments from schema-aware documents."""

    def __init__(self, schema: Schema, *, segment_id: str | None = None) -> None:
        self.schema = schema
        self.segment_id = segment_id or uuid4().hex
        self.created_at = datetime.now(timezone.utc)
        self._postings: MutableMapping[str, MutableMapping[str, MutableMapping[str, list[int]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )
        self._field_lengths: MutableMapping[str, MutableMapping[str, int]] = defaultdict(dict)
        self._stored_fields: MutableMapping[str, dict[str, Any]] = {}
        self._keyword_analyzer = KeywordAnalyzer()
        self._allowed_stored_fields: set[str] = set(_STORED_FIELD_ALLOWLIST)
        self._allowed_stored_fields.add(self.schema.unique_field)

    def add_document(self, document: Mapping[str, Any]) -> str:
        doc_key = self._normalize_unique(document)
        if doc_key in self._stored_fields:
            msg = f"Duplicate document for unique field '{self.schema.unique_field}': {doc_key}"
            raise StorageError(msg)

        stored: dict[str, Any] = {}
        for schema_field in self.schema.fields:
            value = document.get(schema_field.name)
            if schema_field.stored:
                if schema_field.name in self._allowed_stored_fields:
                    normalized = _normalize_stored_value(schema_field.name, value)
                    if normalized not in (None, ""):
                        stored[schema_field.name] = normalized
            if not schema_field.indexed:
                continue
            tokens = self._analyze_field(schema_field, value)
            if not tokens:
                continue
            self._field_lengths[schema_field.name][doc_key] = len(tokens)
            for token in tokens:
                terms = self._postings[schema_field.name][token.text]
                positions = terms[doc_key]
                positions.append(token.position)

        if self.schema.unique_field not in stored:
            unique_value = document.get(self.schema.unique_field)
            normalized_unique = _normalize_stored_value(self.schema.unique_field, unique_value)
            if normalized_unique not in (None, ""):
                stored[self.schema.unique_field] = normalized_unique

        self._stored_fields[doc_key] = stored
        return doc_key

    def build(self) -> IndexSegment:
        postings: dict[str, dict[str, list[Posting]]] = {}
        for field_name, terms in self._postings.items():
            postings[field_name] = {}
            for term, doc_map in terms.items():
                postings[field_name][term] = [
                    Posting(
                        doc_id=doc_id,
                        positions=array("I", positions),
                    )
                    for doc_id, positions in doc_map.items()
                ]

        return IndexSegment(
            schema=self.schema,
            postings=postings,
            stored_fields=dict(self._stored_fields),
            field_lengths={field: dict(lengths) for field, lengths in self._field_lengths.items()},
            segment_id=self.segment_id,
            created_at=self.created_at,
        )

    def _normalize_unique(self, document: Mapping[str, Any]) -> str:
        if self.schema.unique_field not in document:
            msg = f"Document missing unique field '{self.schema.unique_field}'"
            raise StorageError(msg)
        value = document[self.schema.unique_field]
        if value is None:
            msg = f"Unique field '{self.schema.unique_field}' cannot be None"
            raise StorageError(msg)
        return str(value)

    def _analyze_field(self, field: SchemaField, value: Any) -> list[Token]:
        if value is None:
            return []
        if isinstance(field, TextField):
            analyzer = get_analyzer(field.analyzer_name)
            return analyzer(str(value))
        if isinstance(field, KeywordField):
            return self._analyze_keyword(value)
        if isinstance(field, NumericField):
            return self._analyze_numeric(value)
        return []

    def _analyze_keyword(self, value: Any) -> list[Token]:
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, Sequence):
            values = [str(item) for item in value if item is not None]
        else:
            values = [str(value)]

        tokens: list[Token] = []
        for position, entry in enumerate(values):
            normalized = entry.strip()
            if not normalized:
                continue
            analyzed = self._keyword_analyzer(normalized)
            if not analyzed:
                continue
            for offset, token in enumerate(analyzed):
                token.position = position + offset
                tokens.append(token)
        return tokens

    def _analyze_numeric(self, value: Any) -> list[Token]:
        try:
            text = str(value)
        except Exception as exc:  # pragma: no cover - defensive guard
            msg = f"Numeric field value {value!r} could not be stringified: {exc}"
            raise StorageError(msg) from exc
        return [Token(text=text, position=0, start_char=0, end_char=0)]


class JsonSegmentStore:
    """Persist segments as minified JSON payloads with a lightweight manifest."""

    MANIFEST_FILENAME = "manifest.json"
    SEGMENT_SUFFIX = ".json"
    LEGACY_SEGMENT_SUFFIX = ".json.gz"
    DEFAULT_MAX_SEGMENTS = 32
    MAX_SEGMENTS = DEFAULT_MAX_SEGMENTS

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self.directory / self.MANIFEST_FILENAME

    @classmethod
    def set_max_segments(cls, max_segments: int | None) -> None:
        """Override retention when infra config specifies a custom limit."""

        if not max_segments:
            cls.MAX_SEGMENTS = cls.DEFAULT_MAX_SEGMENTS
            return
        cls.MAX_SEGMENTS = max(1, max_segments)

    def save(self, segment: IndexSegment, *, related_files: Sequence[Path | str] | None = None) -> Path:
        """Write the segment to disk (compressed) and update the manifest."""

        if not segment.segment_id:
            raise StorageError("Segment ID is required for persistence")

        manifest = self._load_manifest()
        existing_entry = self._find_manifest_entry(manifest, segment.segment_id)

        if existing_entry:
            # Segment already recorded - ensure latest pointer is correct and reuse existing artifact
            existing_path = self._segment_path(segment.segment_id)
            if not existing_path.exists():
                self._atomic_write_json(existing_path, segment.to_dict())
            self._delete_legacy_segment(segment.segment_id)
            self._ensure_manifest_files(existing_entry, existing_path, related_files)
            manifest["latest_segment_id"] = segment.segment_id
            manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._atomic_write_json(self._manifest_path, manifest)
            return existing_path

        segment_path = self._segment_path(segment.segment_id)
        self._atomic_write_json(segment_path, segment.to_dict())
        self._delete_legacy_segment(segment.segment_id)

        manifest.setdefault("segments", []).append(
            {
                "segment_id": segment.segment_id,
                "created_at": segment.created_at.isoformat(),
                "files": self._manifest_file_names(segment_path, related_files),
            }
        )
        manifest["segments"].sort(key=lambda entry: entry.get("created_at") or "")
        manifest["latest_segment_id"] = segment.segment_id
        self._prune_old_segments(manifest)
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._atomic_write_json(self._manifest_path, manifest)
        return segment_path

    def load(self, segment_id: str) -> IndexSegment | None:
        """Load a segment by ID if it exists on disk."""

        segment_path = self._segment_path(segment_id)
        if not segment_path.exists():
            return None
        data = _load_json_payload(segment_path)
        return IndexSegment.from_dict(data)

    def latest(self) -> IndexSegment | None:
        """Return the latest segment recorded in the manifest."""

        latest_id = self.latest_segment_id()
        if not latest_id:
            return None
        return self.load(latest_id)

    def latest_segment_id(self) -> str | None:
        """Return the latest segment id without loading the full artifact."""

        manifest = self._load_manifest()
        latest_id = manifest.get("latest_segment_id")
        if not latest_id:
            return None
        return str(latest_id)

    def segment_path(self, segment_id: str) -> Path | None:
        """Return the path to the stored segment if it exists."""

        path = self._segment_path(segment_id)
        if path.exists():
            return path
        return None

    def list_segments(self) -> list[dict[str, Any]]:
        """Return all segment entries from the manifest."""
        manifest = self._load_manifest()
        return list(manifest.get("segments", []))

    def _segment_path(self, segment_id: str) -> Path:
        return self.directory / f"{segment_id}{self.SEGMENT_SUFFIX}"

    def _find_manifest_entry(self, manifest: Mapping[str, Any], segment_id: str) -> dict[str, Any] | None:
        for entry in manifest.get("segments", []):
            if entry.get("segment_id") == segment_id:
                return entry
        return None

    def _ensure_manifest_files(
        self,
        entry: MutableMapping[str, Any],
        primary_path: Path,
        related_files: Sequence[Path | str] | None,
    ) -> None:
        files = entry.get("files")
        if not isinstance(files, list):
            files = []
        for name in self._manifest_file_names(primary_path, related_files):
            if name not in files:
                files.append(name)
        entry["files"] = files

    def _manifest_file_names(self, primary_path: Path, related_files: Sequence[Path | str] | None) -> list[str]:
        file_names: list[str] = [primary_path.name]
        if related_files:
            for candidate in related_files:
                if isinstance(candidate, Path):
                    file_names.append(candidate.name)
                elif isinstance(candidate, str) and candidate:
                    file_names.append(Path(candidate).name)
        # Preserve order but drop duplicates
        deduped: list[str] = []
        for name in file_names:
            if name not in deduped:
                deduped.append(name)
        return deduped

    def _load_manifest(self) -> dict[str, Any]:
        if not self._manifest_path.exists():
            return {"segments": []}
        return cast("dict[str, Any]", _load_json_payload(self._manifest_path))

    def prune_to_segment_ids(self, keep_segment_ids: Sequence[str]) -> None:
        """Delete manifest entries and files not present in ``keep_segment_ids``.

        The cleanup runs immediately after indexing so operators don't need to
        rely on the external cleanup CLI to prune stale artifacts.
        """

        keep_ordered = [segment_id for segment_id in keep_segment_ids if segment_id]
        keep_set = set(keep_ordered)
        if not keep_set:
            return

        manifest = self._load_manifest()
        segments = manifest.get("segments", [])
        if not segments:
            return

        kept_entries: list[dict[str, Any]] = []
        removed_entries: list[dict[str, Any]] = []
        for entry in segments:
            segment_id = entry.get("segment_id")
            if segment_id in keep_set:
                kept_entries.append(entry)
            else:
                removed_entries.append(entry)

        if not removed_entries:
            return

        for entry in removed_entries:
            self._delete_entry_files(entry)

        # Preserve manifest order but ensure the entries mirror keep_ordered
        id_to_entry = {entry.get("segment_id"): entry for entry in kept_entries}
        normalized_entries = [id_to_entry[segment_id] for segment_id in keep_ordered if segment_id in id_to_entry]
        manifest["segments"] = normalized_entries
        if normalized_entries:
            manifest["latest_segment_id"] = normalized_entries[-1].get("segment_id")
        else:
            manifest.pop("latest_segment_id", None)
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._atomic_write_json(self._manifest_path, manifest)

    def _prune_old_segments(self, manifest: dict[str, Any]) -> None:
        segments = manifest.get("segments", [])
        if len(segments) <= self.MAX_SEGMENTS:
            return

        excess = segments[: -self.MAX_SEGMENTS]
        manifest["segments"] = segments[-self.MAX_SEGMENTS :]

        for entry in excess:
            self._delete_entry_files(entry)

    def _delete_entry_files(self, entry: Mapping[str, Any]) -> None:
        segment_id = entry.get("segment_id") if isinstance(entry, Mapping) else None
        files = entry.get("files") if isinstance(entry, Mapping) else None

        if isinstance(files, list) and files:
            for relative_name in files:
                if not isinstance(relative_name, str) or not relative_name:
                    continue
                candidate = self.directory / relative_name
                if not candidate.exists():
                    continue
                try:
                    candidate.unlink()
                except OSError:
                    logger.warning("Failed to remove old segment %s", candidate)
            if isinstance(segment_id, str) and segment_id:
                self._delete_legacy_segment(segment_id)
            return

        if not isinstance(segment_id, str) or not segment_id:
            return

        path = self._segment_path(segment_id)
        legacy_path = self.directory / f"{segment_id}{self.LEGACY_SEGMENT_SUFFIX}"
        for candidate in (path, legacy_path):
            if not candidate.exists():
                continue
            try:
                candidate.unlink()
            except OSError:
                logger.warning("Failed to remove old segment %s", candidate)

    def _atomic_write_json(self, path: Path, payload: Any) -> None:
        tmp_path = path.with_suffix(path.suffix + ".tmp") if path.suffix else path.with_name(path.name + ".tmp")
        serialized = _serialize_json_payload(payload)
        tmp_path.write_bytes(serialized)
        tmp_path.replace(path)

    def _delete_legacy_segment(self, segment_id: str) -> None:
        legacy_path = self.directory / f"{segment_id}{self.LEGACY_SEGMENT_SUFFIX}"
        if not legacy_path.exists():
            return
        try:
            legacy_path.unlink()
        except OSError:
            logger.warning("Failed to remove legacy gzip segment %s", legacy_path)
