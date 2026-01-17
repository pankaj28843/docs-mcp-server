"""Tenant-aware indexing helpers for the experimental search stack.

This module builds on top of the in-memory storage primitives to provide a
filesystem-backed indexer that can be driven by CLI tools or schedulers. The
indexer intentionally focuses on deterministic, testable behavior so that
future phases (BM25 ranking, snippet generation) can reuse the same
interfaces.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import urlparse

from docs_mcp_server.search.schema import Schema, create_default_schema
from docs_mcp_server.search.sqlite_storage import SqliteSegmentWriter
from docs_mcp_server.search.storage_factory import create_segment_store
from docs_mcp_server.utils.front_matter import parse_front_matter


logger = logging.getLogger(__name__)

_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_METADATA_DIRNAME = "__docs_metadata"
_SEGMENT_FORMAT_VERSION = "v4-postings-doclen"


@dataclass(frozen=True)
class TenantIndexingContext:
    """Immutable context describing how to index a single tenant."""

    codename: str
    docs_root: Path
    segments_dir: Path
    source_type: str = "online"
    schema: Schema = field(default_factory=create_default_schema)
    url_whitelist_prefixes: tuple[str, ...] = field(default_factory=tuple)
    url_blacklist_prefixes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def metadata_root(self) -> Path:
        return self.docs_root / _METADATA_DIRNAME


@dataclass(frozen=True)
class IndexBuildResult:
    """Outcome of a tenant indexing run."""

    documents_indexed: int
    documents_skipped: int
    errors: tuple[str, ...]
    segment_ids: tuple[str, ...]
    segment_paths: tuple[Path, ...]


@dataclass(frozen=True)
class FingerprintAudit:
    """Summary of the latest fingerprint audit."""

    fingerprint: str | None
    current_segment_id: str | None
    needs_rebuild: bool


_SKIP_MARKDOWN_DIRS = {
    "__docs_metadata",
    "__search_segments",
    "__scheduler_meta",
    ".git",
    ".hg",
    ".svn",
}


class TenantIndexer:
    """Coordinate extraction + segment persistence for one tenant."""

    def __init__(self, context: TenantIndexingContext) -> None:
        self.context = context
        self._store = create_segment_store(context.segments_dir)

    def build_segment(
        self,
        *,
        changed_paths: Sequence[str] | None = None,
        limit: int | None = None,
        changed_only: bool = False,
        persist: bool = True,
    ) -> IndexBuildResult:
        """Build a new segment, optionally filtering to changed files.

        Args:
            changed_paths: Optional iterable of markdown/metadata paths (relative to docs root)
                that should be forced into the build regardless of mtime checks.
            limit: Cap the number of documents processed (useful for smoke tests).
            changed_only: Skip documents whose metadata + markdown mtime predates the
                previously persisted segment (if any).
            persist: When False, return an in-memory build result without writing the
                JSON segment/manifest to disk. This powers CLI dry-run flows.
        """

        normalized_filters = self._normalize_paths(changed_paths)
        latest_segment = self._store.latest()
        last_built_at = latest_segment.created_at if latest_segment else None

        writer = SqliteSegmentWriter(self.context.schema)
        fingerprinter = _DocsFingerprintBuilder(self.context.schema)
        documents_indexed = 0
        documents_skipped = 0
        errors: list[str] = []

        seen_markdown_paths: set[Path] = set()

        def process_payload(payload: _DocumentPayload) -> None:
            nonlocal documents_indexed, documents_skipped

            markdown_rel = self._relative_to_root(payload.markdown_path)
            metadata_rel = self._relative_to_root(payload.metadata_path) if payload.metadata_path is not None else None

            if (
                normalized_filters
                and markdown_rel not in normalized_filters
                and (metadata_rel is None or metadata_rel not in normalized_filters)
            ):
                documents_skipped += 1
                return

            if self.context.source_type == "online" and not self._url_allowed(payload.url):
                documents_skipped += 1
                return

            if changed_only and last_built_at and not self._has_changed(payload, last_built_at):
                documents_skipped += 1
                return

            try:
                doc_key = writer.add_document(payload.record)
                fingerprinter.add_document(doc_key, payload.record)
            except ValueError as exc:
                logger.warning("Failed to index %s: %s", payload.source_hint, exc)
                errors.append(f"{payload.url}: {exc}")
                documents_skipped += 1
                return

            documents_indexed += 1
            return

        if self.context.source_type == "online":
            for metadata_path in self._discover_metadata_files():
                if limit is not None and documents_indexed >= limit:
                    break

                try:
                    document_payload = self._load_document_from_metadata(metadata_path)
                except DocumentLoadError as exc:  # pragma: no cover - defensive log
                    logger.debug("Skipping %s: %s", metadata_path, exc)
                    errors.append(str(exc))
                    documents_skipped += 1
                    continue

                seen_markdown_paths.add(document_payload.markdown_path.resolve())

                process_payload(document_payload)

        for markdown_path in self._discover_markdown_files():
            if limit is not None and documents_indexed >= limit:
                break

            resolved_markdown = markdown_path.resolve()
            if resolved_markdown in seen_markdown_paths:
                continue

            try:
                document_payload = self._load_document_from_markdown(markdown_path)
            except DocumentLoadError as exc:
                logger.debug("Skipping %s: %s", markdown_path, exc)
                errors.append(str(exc))
                documents_skipped += 1
                continue

            seen_markdown_paths.add(resolved_markdown)

            process_payload(document_payload)

        if documents_indexed == 0:
            return IndexBuildResult(
                documents_indexed=0,
                documents_skipped=documents_skipped,
                errors=tuple(errors),
                segment_ids=(),
                segment_paths=(),
            )

        fingerprint = fingerprinter.digest()
        if fingerprint:
            writer.segment_id = fingerprint

        segment_paths: tuple[Path, ...] = ()
        segment_id: str | None = writer.segment_id if documents_indexed > 0 else None
        if persist:
            segment_data = writer.build()
            segment_path = self._store.save(segment_data)
            self._store.prune_to_segment_ids((segment_data["segment_id"],))
            segment_paths = (segment_path,)
            segment_id = segment_data["segment_id"]

        segment_ids: tuple[str, ...] = (segment_id,) if segment_id else ()
        return IndexBuildResult(
            documents_indexed=documents_indexed,
            documents_skipped=documents_skipped,
            errors=tuple(errors),
            segment_ids=segment_ids,
            segment_paths=segment_paths,
        )

    def compute_fingerprint(self) -> str | None:
        """Return the deterministic fingerprint without persisting a segment."""

        result = self.build_segment(persist=False)
        if not result.segment_ids:
            return None
        return result.segment_ids[0]

    def fingerprint_audit(self) -> FingerprintAudit:
        """Compare computed fingerprint with the manifest state."""

        fingerprint = self.compute_fingerprint()
        current_segment_id = self._store.latest_segment_id()
        if not fingerprint:
            return FingerprintAudit(fingerprint=None, current_segment_id=current_segment_id, needs_rebuild=False)

        if current_segment_id is None:
            return FingerprintAudit(fingerprint=fingerprint, current_segment_id=None, needs_rebuild=True)

        needs_rebuild = current_segment_id != fingerprint
        return FingerprintAudit(
            fingerprint=fingerprint,
            current_segment_id=current_segment_id,
            needs_rebuild=needs_rebuild,
        )

    # --- internal helpers -------------------------------------------------

    def _discover_metadata_files(self) -> Iterator[Path]:
        root = self.context.metadata_root
        if not root.exists():
            logger.warning("Metadata directory missing for tenant '%s': %s", self.context.codename, root)
            return iter(())

        rg_cmd = [
            "rg",
            "--files",
            "--hidden",
            "--iglob",
            "*.meta.json",
            str(root),
        ]
        try:
            completed = subprocess.run(rg_cmd, capture_output=True, check=True, text=True)
            for line in completed.stdout.splitlines():
                candidate = Path(line.strip())
                if candidate.is_file():
                    yield candidate
        except FileNotFoundError:
            logger.debug("ripgrep not available; falling back to Path.rglob")
            yield from root.rglob("*.meta.json")
        except subprocess.CalledProcessError as exc:  # pragma: no cover - unexpected
            logger.debug("ripgrep failed (%s); falling back to Path.rglob", exc)
            yield from root.rglob("*.meta.json")

    def _discover_markdown_files(self) -> Iterator[Path]:
        root = self.context.docs_root
        if not root.exists():
            return iter(())

        for markdown_path in root.rglob("*.md"):
            try:
                relative_parts = markdown_path.relative_to(root).parts[:-1]
            except ValueError:
                relative_parts = ()

            if any(part in _SKIP_MARKDOWN_DIRS for part in relative_parts):
                continue

            yield markdown_path

    def _load_document_from_metadata(self, metadata_path: Path) -> _DocumentPayload:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        url = payload.get("url")
        if not url:
            raise DocumentLoadError(f"Metadata missing url field: {metadata_path}")

        meta_info = payload.get("metadata", {})
        markdown_path = self._resolve_markdown_path(metadata_path, meta_info)
        if not markdown_path.exists():
            raise DocumentLoadError(f"Markdown missing for {url}: {markdown_path}")

        return self._build_payload(
            markdown_path=markdown_path,
            metadata_path=metadata_path,
            metadata_payload=payload,
        )

    def _load_document_from_markdown(self, markdown_path: Path) -> _DocumentPayload:
        if not markdown_path.exists():
            raise DocumentLoadError(f"Markdown missing: {markdown_path}")

        return self._build_payload(markdown_path=markdown_path, metadata_path=None, metadata_payload=None)

    def _build_payload(
        self,
        *,
        markdown_path: Path,
        metadata_path: Path | None,
        metadata_payload: dict[str, Any] | None,
    ) -> _DocumentPayload:
        raw_markdown = markdown_path.read_text(encoding="utf-8")
        front_matter, markdown = parse_front_matter(raw_markdown)

        tiered_headings = _extract_tiered_headings(markdown)
        # Backward compatible: headings field contains all headings H3+
        headings = tiered_headings.h3_plus
        excerpt = _extract_excerpt(markdown)

        metadata = metadata_payload or {}
        meta_info = metadata.get("metadata", {}) if metadata_payload else front_matter

        url = metadata.get("url") or front_matter.get("url") or self._default_url_for(markdown_path)
        title = metadata.get("title") or front_matter.get("title") or _derive_title(markdown, markdown_path)
        tags = _coerce_tags(front_matter.get("tags"))
        language = _detect_language(url, front_matter)

        if not url:
            raise DocumentLoadError(f"Unable to derive url for {markdown_path}")

        document_record = {
            "url": url,
            "url_path": _extract_url_path(url),
            "title": title,
            "headings_h1": tiered_headings.h1,
            "headings_h2": tiered_headings.h2,
            "headings": headings,
            "body": markdown,
            "path": str(self._relative_to_root(markdown_path)),
            "tags": tags,
            "excerpt": excerpt,
            "language": language,
            "timestamp": _resolve_timestamp(meta_info, markdown_path),
        }

        return _DocumentPayload(
            record=document_record,
            metadata_path=metadata_path,
            markdown_path=markdown_path,
            url=url,
            source_hint=metadata_path or markdown_path,
        )

    def _has_changed(self, payload: _DocumentPayload, last_built_at: datetime) -> bool:
        threshold = last_built_at.timestamp()
        markdown_mtime = payload.markdown_path.stat().st_mtime
        meta_mtime = payload.metadata_path.stat().st_mtime if payload.metadata_path else 0
        return meta_mtime > threshold or markdown_mtime > threshold

    def _resolve_markdown_path(self, metadata_path: Path, meta_info: dict[str, Any]) -> Path:
        rel_path = meta_info.get("markdown_rel_path")
        if isinstance(rel_path, str) and rel_path.strip():
            return (self.context.docs_root / rel_path).resolve()
        return self._candidate_markdown_path(metadata_path)

    def _candidate_markdown_path(self, metadata_path: Path) -> Path:
        metadata_root = self.context.metadata_root
        try:
            relative = metadata_path.relative_to(metadata_root)
        except ValueError:
            relative = metadata_path.name
        relative_str = str(relative)
        if relative_str.endswith(".meta.json"):
            relative_str = relative_str[: -len(".meta.json")] + ".md"
        return (self.context.docs_root / relative_str).resolve()

    def _default_url_for(self, markdown_path: Path) -> str:
        return markdown_path.resolve().as_uri()

    def _relative_to_root(self, path: Path) -> Path:
        try:
            return path.resolve().relative_to(self.context.docs_root.resolve())
        except ValueError:
            return path.resolve()

    def _normalize_paths(self, candidates: Sequence[str] | None) -> set[Path]:
        if not candidates:
            return set()
        docs_root = self.context.docs_root.resolve()
        normalized: set[Path] = set()
        for entry in candidates:
            candidate_path = Path(entry)
            if candidate_path.is_absolute():
                try:
                    normalized.add(candidate_path.resolve().relative_to(docs_root))
                except ValueError:
                    normalized.add(candidate_path.resolve())
            else:
                normalized.add(candidate_path)
        return normalized

    def _url_allowed(self, url: str) -> bool:
        """Check whether a document URL passes whitelist/blacklist filters."""

        normalized = url.strip() if url else ""
        whitelist = self.context.url_whitelist_prefixes
        blacklist = self.context.url_blacklist_prefixes

        if whitelist:
            if not normalized:
                return False
            if not any(normalized.startswith(prefix) for prefix in whitelist):
                return False

        if not normalized:
            return True  # No whitelist configured; empty URLs already handled elsewhere

        if blacklist and any(normalized.startswith(prefix) for prefix in blacklist):
            return False

        return True


@dataclass(frozen=True)
class _DocumentPayload:
    record: dict[str, Any]
    metadata_path: Path | None
    markdown_path: Path
    url: str
    source_hint: Path


@dataclass(frozen=True)
class TieredHeadings:
    """Headings separated by level for weighted search."""

    h1: str  # H1 headings (highest weight)
    h2: str  # H2 headings (medium weight)
    h3_plus: str  # H3-H6 headings (lower weight)


def _extract_tiered_headings(markdown: str) -> TieredHeadings:
    """Extract headings separated by level for tiered boosting."""
    h1_list: list[str] = []
    h2_list: list[str] = []
    h3_plus_list: list[str] = []

    for match in _HEADING_PATTERN.finditer(markdown):
        hashes = match.group(1)
        text = match.group(2)
        cleaned = _strip_heading_tail(text)
        if not cleaned:
            continue

        level = len(hashes)
        if level == 1:
            h1_list.append(cleaned)
        elif level == 2:
            h2_list.append(cleaned)
        else:  # level 3-6
            h3_plus_list.append(cleaned)

    return TieredHeadings(
        h1="\n".join(h1_list),
        h2="\n".join(h2_list),
        h3_plus="\n".join(h3_plus_list),
    )


def _extract_headings(markdown: str) -> str:
    """Extract all headings (backward compatible - returns all headings concatenated)."""
    tiered = _extract_tiered_headings(markdown)
    all_headings = [tiered.h1, tiered.h2, tiered.h3_plus]
    return "\n".join(h for h in all_headings if h)


def _strip_heading_tail(value: str) -> str:
    text = re.sub(r"\s*\[¶\]\(.*?\)$", "", value.strip())
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_excerpt(markdown: str, *, max_length: int = 320) -> str:
    for paragraph in _iterate_paragraphs(markdown):
        normalized = re.sub(r"\s+", " ", paragraph).strip()
        if normalized:
            return normalized[:max_length]
    return ""


def _derive_title(markdown: str, markdown_path: Path) -> str:
    headings = _extract_headings(markdown)
    if headings:
        return headings.splitlines()[0]
    stem = markdown_path.stem.replace("-", " ").strip()
    return stem or markdown_path.name


def _coerce_tags(candidate: Any) -> list[str]:
    if isinstance(candidate, list):
        return [str(item) for item in candidate]
    if isinstance(candidate, str):
        return [candidate]
    return []


def _iterate_paragraphs(markdown: str) -> Iterable[str]:
    block: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            if block:
                yield " ".join(block)
                block = []
            continue
        if stripped.startswith(("#", "```")):
            if block:
                yield " ".join(block)
                block = []
            continue
        block.append(stripped)
    if block:
        yield " ".join(block)


def _resolve_timestamp(meta_info: Mapping[str, Any], markdown_path: Path) -> int:
    raw = meta_info.get("last_fetched_at") or meta_info.get("indexed_at")
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except ValueError:  # pragma: no cover - defensive
            pass
    return int(markdown_path.stat().st_mtime)


def _extract_url_path(url: str) -> str:
    """Extract the path component from a URL for searchable segments.

    Examples:
        "https://docs.djangoproject.com/en/5.1/topics/forms/" -> "/en/5.1/topics/forms/"
        "file:///path/to/doc.md" -> "/path/to/doc.md"
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        return parsed.path or ""
    except ValueError:  # pragma: no cover - defensive
        return ""


class _DocsFingerprintBuilder:
    """Deterministically hash indexed documents + schema for idempotent segments."""

    def __init__(self, schema: Schema) -> None:
        serialized_schema = json.dumps(
            schema.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        self._schema_digest = hashlib.sha256(serialized_schema).hexdigest()
        self._format_digest = hashlib.sha256(_SEGMENT_FORMAT_VERSION.encode("utf-8")).hexdigest()
        self._doc_digests: list[tuple[str, str]] = []

    def add_document(self, doc_id: str, record: Mapping[str, Any]) -> None:
        serialized_record = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(serialized_record.encode("utf-8")).hexdigest()
        self._doc_digests.append((doc_id, digest))

    def digest(self) -> str:
        if not self._doc_digests:
            return ""
        root = hashlib.sha256()
        root.update(self._format_digest.encode("ascii"))
        root.update(self._schema_digest.encode("ascii"))
        for doc_id, digest in sorted(self._doc_digests, key=lambda item: item[0]):
            root.update(doc_id.encode("utf-8"))
            root.update(digest.encode("ascii"))
        return root.hexdigest()


# Language detection patterns - auto-detect from URL, no config needed
_LANGUAGE_PATTERNS = {
    # URL path patterns for language codes
    "/ja/": "ja",
    "/jp/": "ja",
    "/zh/": "zh",
    "/zh-cn/": "zh",
    "/zh-tw/": "zh",
    "/ko/": "ko",
    "/de/": "de",
    "/fr/": "fr",
    "/es/": "es",
    "/pt/": "pt",
    "/ru/": "ru",
    "/it/": "it",
    "/en/": "en",
    # Subdomain patterns
    "ja.": "ja",
    "jp.": "ja",
    "zh.": "zh",
    "ko.": "ko",
    "de.": "de",
    "fr.": "fr",
}


def _detect_language(url: str, front_matter: Mapping[str, Any]) -> str:
    """Auto-detect document language from URL patterns or front matter.

    Priority:
    1. Explicit 'language' or 'lang' in front matter
    2. URL path patterns like /ja/, /zh/, /en/
    3. URL subdomain patterns like ja.docs.example.com
    4. Default to 'en' (English) - smart default for most docs

    This is a zero-config approach - language is detected automatically.
    """
    # Check front matter first
    lang = front_matter.get("language") or front_matter.get("lang")
    if isinstance(lang, str) and lang.strip():
        return lang.strip().lower()[:5]  # e.g., "en", "ja", "zh-cn"

    if not url:
        return "en"

    url_lower = url.lower()

    # Check URL path patterns
    for pattern, lang_code in _LANGUAGE_PATTERNS.items():
        if pattern in url_lower:
            return lang_code

    # Default to English - most technical docs are in English
    return "en"


class DocumentLoadError(RuntimeError):
    """Raised when filesystem metadata cannot be converted into a record."""
