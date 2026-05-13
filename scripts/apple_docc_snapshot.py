#!/usr/bin/env python3
"""Build a filesystem snapshot of Apple Developer DocC JSON documentation.

Apple Developer Documentation renders from JavaScript and DocC JSON endpoints under
``/tutorials/data/documentation``. The generic online crawler sees the shell page
but not the complete API graph. This operator tool discovers the DocC JSON graph,
renders useful Markdown, and stores it under a filesystem tenant root so the
normal search indexer can build SQLite segments.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
from typing import Any
from urllib.parse import quote, urlsplit

import aiohttp
import yaml


LOGGER = logging.getLogger(__name__)

APPLE_DEVELOPER_BASE_URL = "https://developer.apple.com"
APPLE_DOCC_DATA_BASE_URL = f"{APPLE_DEVELOPER_BASE_URL}/tutorials/data/documentation"
DEFAULT_START_DATA_URLS = (
    f"{APPLE_DEVELOPER_BASE_URL}/tutorials/data/documentation.json",
    f"{APPLE_DOCC_DATA_BASE_URL}/technologies.json",
)
DEFAULT_REQUIRED_DOCUMENTATION_URLS = (
    f"{APPLE_DEVELOPER_BASE_URL}/documentation/SwiftUI",
    f"{APPLE_DEVELOPER_BASE_URL}/documentation/SwiftUI/View-fundamentals",
    f"{APPLE_DEVELOPER_BASE_URL}/documentation/FoundationModels/generating-content-and-performing-tasks-with-foundation-models",
    f"{APPLE_DEVELOPER_BASE_URL}/documentation/Accessibility",
    f"{APPLE_DEVELOPER_BASE_URL}/documentation/Xcode/writing-code-with-intelligence-in-xcode",
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

_DOC_IDENTIFIER_PATTERN = re.compile(r"doc://[^\s\"']*/documentation/([^\s\"'#]+)")
_DOC_PATH_PATTERN = re.compile(r"^/documentation/([^#?]+)")
_FRONT_MATTER_PATTERN = re.compile(r"^-----\s*\n(.*?)\n-----\s*\n", re.DOTALL)


@dataclass(frozen=True)
class AppleDocCSnapshotOptions:
    """Configuration for one Apple DocC snapshot run."""

    docs_root: Path = Path("mcp-data/apple-developer")
    snapshot_subdir: str = "apple-docs"
    urls_file: Path = Path("tmp/apple-docc-snapshot/apple-developer/urls.json")
    max_docs: int = 20_000
    discovery_limit: int = 20_000
    concurrency: int = 24
    clean: bool = False
    discover_only: bool = False
    build_only: bool = False
    dry_run: bool = False
    user_agent: str = DEFAULT_USER_AGENT
    start_data_urls: tuple[str, ...] = DEFAULT_START_DATA_URLS
    required_documentation_urls: tuple[str, ...] = DEFAULT_REQUIRED_DOCUMENTATION_URLS

    @property
    def snapshot_dir(self) -> Path:
        """Directory containing generated Markdown documents."""
        return self.docs_root / self.snapshot_subdir


@dataclass(frozen=True)
class SnapshotResult:
    """Summary of a snapshot run."""

    discovered_urls: int
    selected_urls: int
    written_docs: int
    skipped_docs: int
    output_dir: Path
    urls_file: Path


@dataclass(frozen=True)
class RenderedDocument:
    """Rendered Markdown plus metadata for one documentation page."""

    url: str
    title: str
    markdown: str


@dataclass
class _DiscoveryState:
    seen_data_urls: set[str] = field(default_factory=set)
    seen_doc_paths: set[str] = field(default_factory=set)
    queued_data_urls: set[str] = field(default_factory=set)


class AppleDocCSnapshotError(RuntimeError):
    """Raised when a snapshot cannot be produced."""


async def build_apple_docc_snapshot(options: AppleDocCSnapshotOptions) -> SnapshotResult:
    """Discover Apple DocC pages and render them as Markdown files."""
    options.docs_root.mkdir(parents=True, exist_ok=True)
    options.urls_file.parent.mkdir(parents=True, exist_ok=True)

    discovered_urls: tuple[str, ...]
    if options.build_only:
        discovered_urls = _read_urls_file(options.urls_file)
    else:
        discovered_urls = await discover_documentation_urls(options)
        if not options.dry_run:
            options.urls_file.write_text(json.dumps(discovered_urls, indent=2) + "\n", encoding="utf-8")

    selected_urls = select_documentation_urls(
        discovered_urls,
        required_urls=options.required_documentation_urls,
        max_docs=options.max_docs,
    )

    if options.discover_only:
        return SnapshotResult(
            discovered_urls=len(discovered_urls),
            selected_urls=len(selected_urls),
            written_docs=0,
            skipped_docs=0,
            output_dir=options.snapshot_dir,
            urls_file=options.urls_file,
        )

    if options.clean and not options.dry_run:
        _remove_snapshot_dir(options.docs_root, options.snapshot_dir)
    if not options.dry_run:
        options.snapshot_dir.mkdir(parents=True, exist_ok=True)

    written, skipped = await render_snapshot_documents(options, selected_urls)
    return SnapshotResult(
        discovered_urls=len(discovered_urls),
        selected_urls=len(selected_urls),
        written_docs=written,
        skipped_docs=skipped,
        output_dir=options.snapshot_dir,
        urls_file=options.urls_file,
    )


async def discover_documentation_urls(options: AppleDocCSnapshotOptions) -> tuple[str, ...]:
    """Discover documentation URLs by walking Apple DocC JSON references."""
    headers = {"User-Agent": options.user_agent, "Accept": "application/json,text/plain,*/*"}
    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(limit=options.concurrency, limit_per_host=options.concurrency)
    queue: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()
    state = _DiscoveryState()

    for data_url in options.start_data_urls:
        await _queue_data_url(queue, state, data_url, source_doc_path=None)

    async with aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector) as session:
        workers = [
            asyncio.create_task(_discovery_worker(session, queue, state, options)) for _ in range(options.concurrency)
        ]
        await asyncio.gather(*workers)

    urls = tuple(_documentation_url_from_path(path) for path in sorted(state.seen_doc_paths))
    LOGGER.info("Discovered %s Apple documentation URLs", len(urls))
    return urls


async def render_snapshot_documents(options: AppleDocCSnapshotOptions, urls: Sequence[str]) -> tuple[int, int]:
    """Fetch selected DocC JSON pages and write rendered Markdown."""
    headers = {"User-Agent": options.user_agent, "Accept": "application/json,text/plain,*/*"}
    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(limit=options.concurrency, limit_per_host=options.concurrency)
    semaphore = asyncio.Semaphore(options.concurrency)
    written = 0
    skipped = 0

    async with aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector) as session:

        async def process(url: str) -> None:
            nonlocal written, skipped
            async with semaphore:
                document = await fetch_and_render_document(session, url)
                if document is None:
                    skipped += 1
                    return
                if not options.dry_run:
                    _write_rendered_document(options.snapshot_dir, document)
                written += 1
                if written % 500 == 0:
                    LOGGER.info("Rendered %s Apple DocC pages (skipped=%s)", written, skipped)

        await asyncio.gather(*(process(url) for url in urls))

    return written, skipped


async def fetch_and_render_document(session: aiohttp.ClientSession, url: str) -> RenderedDocument | None:
    """Fetch one DocC JSON page and render it to Markdown."""
    data_url = documentation_url_to_data_url(url)
    if data_url is None:
        return None

    try:
        async with session.get(data_url) as response:
            if response.status != 200 or "json" not in response.headers.get("content-type", ""):
                return None
            payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError):
        return None

    document = render_docc_json(payload, url)
    if len(document.markdown.split()) < 20:
        return None
    return document


def render_docc_json(payload: dict[str, Any], url: str) -> RenderedDocument:
    """Render Apple DocC JSON into searchable Markdown."""
    references = payload.get("references") if isinstance(payload.get("references"), dict) else {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    title = str(metadata.get("title") or url.rstrip("/").rsplit("/", 1)[-1])
    role = str(metadata.get("roleHeading") or metadata.get("role") or payload.get("kind") or "Documentation")
    modules = _join_named_items(metadata.get("modules"))
    platforms = _join_named_items(metadata.get("platforms"))

    lines = [f"# {title}", _summary_line(role, modules, platforms)]
    abstract = _collapse_whitespace(_inline_text(payload.get("abstract"), references))
    if abstract:
        lines.append(abstract)

    declaration = _fragments_text(metadata.get("fragments"))
    if declaration:
        lines.append(f"```swift\n{declaration}\n```")

    lines.extend(_render_primary_sections(payload.get("primaryContentSections"), references))
    lines.extend(_render_named_sections(payload.get("sections"), references))
    lines.extend(_render_identifier_sections(payload.get("topicSections"), references, "Topics"))
    lines.extend(_render_identifier_sections(payload.get("relationshipsSections"), references, "Relationships"))
    lines.extend(_render_identifier_sections(payload.get("seeAlsoSections"), references, "See also"))
    lines.extend(_render_reference_index(references))

    markdown = "\n\n".join(line.strip() for line in lines if line.strip()) + "\n"
    return RenderedDocument(url=url, title=title, markdown=markdown)


def select_documentation_urls(
    discovered_urls: Sequence[str],
    *,
    required_urls: Sequence[str],
    max_docs: int,
) -> tuple[str, ...]:
    """Return deduplicated URLs, preferring Apple's canonical mixed-case paths."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for url in (*required_urls, *discovered_urls):
        path = documentation_url_to_path(url)
        if path:
            grouped[_url_dedupe_key(url)].append(url)

    selected = [sorted(set(urls), key=_canonical_url_sort_key)[0] for urls in grouped.values()]

    required_keys = {_url_dedupe_key(url) for url in required_urls if documentation_url_to_path(url)}
    selected.sort(key=lambda url: (0 if _url_dedupe_key(url) in required_keys else 1, url.lower()))
    return tuple(selected[:max_docs])


def documentation_url_to_path(url: str) -> str | None:
    """Extract the path below ``/documentation/`` from an Apple documentation URL."""
    parsed = urlsplit(url)
    prefix = "/documentation/"
    if parsed.netloc != "developer.apple.com" or not parsed.path.startswith(prefix):
        return None
    path = parsed.path[len(prefix) :].strip("/")
    return _normalize_doc_path(path)


def documentation_url_to_data_url(url: str) -> str | None:
    """Map a public Apple documentation URL to its DocC JSON endpoint."""
    path = documentation_url_to_path(url)
    if not path:
        return None
    encoded = "/".join(quote(part, safe="-._~():") for part in path.split("/"))
    return f"{APPLE_DOCC_DATA_BASE_URL}/{encoded}.json"


def extract_documentation_paths(payload: Any) -> set[str]:
    """Extract documentation paths from a DocC JSON object."""
    found: set[str] = set()

    def add(raw_path: str) -> None:
        normalized = _normalize_doc_path(raw_path)
        if normalized:
            found.add(normalized)

    def walk(value: Any) -> None:
        if isinstance(value, str):
            for match in _DOC_IDENTIFIER_PATTERN.finditer(value):
                add(match.group(1))
            if match := _DOC_PATH_PATTERN.match(value):
                add(match.group(1))
            return
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
            return
        if isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return found


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the Apple DocC snapshot CLI parser."""
    parser = argparse.ArgumentParser(description="Build a local Apple Developer DocC Markdown snapshot")
    parser.add_argument("--docs-root", type=Path, default=Path("mcp-data/apple-developer"))
    parser.add_argument("--snapshot-subdir", default="apple-docs")
    parser.add_argument("--urls-file", type=Path, default=Path("tmp/apple-docc-snapshot/apple-developer/urls.json"))
    parser.add_argument("--max-docs", type=int, default=20_000)
    parser.add_argument("--discovery-limit", type=int, default=20_000)
    parser.add_argument("--concurrency", type=int, default=24)
    parser.add_argument("--required-url", action="append", default=[])
    parser.add_argument(
        "--clean", action="store_true", help="Remove the generated snapshot subdirectory before writing"
    )
    parser.add_argument(
        "--discover-only", action="store_true", help="Discover URLs and write --urls-file without rendering docs"
    )
    parser.add_argument("--build-only", action="store_true", help="Render docs from an existing --urls-file")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and render without writing files")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Apple DocC snapshot CLI."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_argument_parser().parse_args(argv)
    options = AppleDocCSnapshotOptions(
        docs_root=args.docs_root,
        snapshot_subdir=args.snapshot_subdir,
        urls_file=args.urls_file,
        max_docs=args.max_docs,
        discovery_limit=args.discovery_limit,
        concurrency=args.concurrency,
        clean=args.clean,
        discover_only=args.discover_only,
        build_only=args.build_only,
        dry_run=args.dry_run,
        user_agent=args.user_agent,
        required_documentation_urls=(*DEFAULT_REQUIRED_DOCUMENTATION_URLS, *tuple(args.required_url)),
    )

    try:
        result = asyncio.run(build_apple_docc_snapshot(options))
    except AppleDocCSnapshotError as exc:
        LOGGER.error("Apple DocC snapshot failed: %s", exc)
        return 1

    LOGGER.info("Apple DocC snapshot complete")
    LOGGER.info("  discovered URLs: %s", result.discovered_urls)
    LOGGER.info("  selected URLs:   %s", result.selected_urls)
    LOGGER.info("  written docs:    %s", result.written_docs)
    LOGGER.info("  skipped docs:    %s", result.skipped_docs)
    LOGGER.info("  output dir:      %s", result.output_dir)
    LOGGER.info("  urls file:       %s", result.urls_file)
    return 0 if options.discover_only or result.written_docs > 0 else 1


async def _discovery_worker(
    session: aiohttp.ClientSession,
    queue: asyncio.Queue[tuple[str, str | None]],
    state: _DiscoveryState,
    options: AppleDocCSnapshotOptions,
) -> None:
    while len(state.seen_doc_paths) < options.discovery_limit:
        try:
            data_url, source_doc_path = await asyncio.wait_for(queue.get(), timeout=3)
        except TimeoutError:
            return
        if data_url in state.seen_data_urls:
            queue.task_done()
            continue
        state.seen_data_urls.add(data_url)
        payload = await _fetch_json(session, data_url)
        if payload is not None:
            if source_doc_path:
                state.seen_doc_paths.add(source_doc_path)
            await _queue_discovered_paths(queue, state, payload, options.discovery_limit)
        if len(state.seen_data_urls) % 500 == 0:
            LOGGER.info(
                "Discovery fetched=%s docs=%s queued=%s",
                len(state.seen_data_urls),
                len(state.seen_doc_paths),
                queue.qsize(),
            )
        queue.task_done()


async def _fetch_json(session: aiohttp.ClientSession, url: str) -> dict[str, Any] | None:
    try:
        async with session.get(url) as response:
            if response.status != 200 or "json" not in response.headers.get("content-type", ""):
                return None
            payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


async def _queue_discovered_paths(
    queue: asyncio.Queue[tuple[str, str | None]],
    state: _DiscoveryState,
    payload: dict[str, Any],
    discovery_limit: int,
) -> None:
    for path in sorted(extract_documentation_paths(payload)):
        if len(state.seen_doc_paths) + queue.qsize() >= discovery_limit * 2:
            return
        if path in state.seen_doc_paths:
            continue
        await _queue_data_url(queue, state, _data_url_from_doc_path(path), source_doc_path=path)


async def _queue_data_url(
    queue: asyncio.Queue[tuple[str, str | None]],
    state: _DiscoveryState,
    data_url: str,
    *,
    source_doc_path: str | None,
) -> None:
    if data_url in state.seen_data_urls or data_url in state.queued_data_urls:
        return
    state.queued_data_urls.add(data_url)
    await queue.put((data_url, source_doc_path))


def _normalize_doc_path(path: str) -> str | None:
    normalized = path.strip().strip("/")
    if not normalized:
        return None
    parts = tuple(part for part in normalized.split("/") if part)
    if not parts or any(part.startswith("_") for part in parts):
        return None
    return "/".join(parts)


def _documentation_url_from_path(path: str) -> str:
    encoded = "/".join(quote(part, safe="-._~():") for part in path.split("/"))
    return f"{APPLE_DEVELOPER_BASE_URL}/documentation/{encoded}"


def _data_url_from_doc_path(path: str) -> str:
    encoded = "/".join(quote(part, safe="-._~():") for part in path.split("/"))
    return f"{APPLE_DOCC_DATA_BASE_URL}/{encoded}.json"


def _read_urls_file(path: Path) -> tuple[str, ...]:
    if not path.exists():
        raise AppleDocCSnapshotError(f"URLs file does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(url, str) for url in payload):
        raise AppleDocCSnapshotError(f"URLs file must contain a JSON list of strings: {path}")
    return tuple(payload)


def _remove_snapshot_dir(docs_root: Path, snapshot_dir: Path) -> None:
    root = docs_root.resolve()
    target = snapshot_dir.resolve()
    if target == root or root not in target.parents:
        raise AppleDocCSnapshotError(f"Refusing to remove snapshot outside docs root: {snapshot_dir}")
    if target.exists():
        shutil.rmtree(target)


def _write_rendered_document(snapshot_dir: Path, document: RenderedDocument) -> None:
    output_path = _output_path_for_url(snapshot_dir, document.url)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "last_fetched_at": datetime.now(UTC).isoformat(),
        "source": "Apple DocC JSON",
        "title": document.title,
        "url": document.url,
    }
    output_path.write_text(_front_matter(metadata) + document.markdown, encoding="utf-8")


def _output_path_for_url(snapshot_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()
    return snapshot_dir / digest[:2] / f"{digest}.md"


def _front_matter(metadata: dict[str, str]) -> str:
    yaml_text = yaml.safe_dump(metadata, sort_keys=True, allow_unicode=True).rstrip("\n")
    return f"-----\n{yaml_text}\n-----\n"


def _url_dedupe_key(url: str) -> str:
    return url.rstrip("/").lower()


def _canonical_url_sort_key(url: str) -> tuple[int, int, str]:
    uppercase_count = sum(1 for char in url if char.isupper())
    return (-uppercase_count, len(url), url)


def _join_named_items(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    names = [str(item.get("name")) for item in value if isinstance(item, dict) and item.get("name")]
    return ", ".join(names)


def _summary_line(role: str, modules: str, platforms: str) -> str:
    parts = [role]
    if modules:
        parts.append(f"Modules: {modules}")
    if platforms:
        parts.append(f"Platforms: {platforms}")
    return "; ".join(parts)


def _render_primary_sections(sections: Any, references: dict[str, Any]) -> list[str]:
    rendered: list[str] = []
    if not isinstance(sections, list):
        return rendered
    for section in sections:
        if not isinstance(section, dict):
            continue
        if section.get("kind") == "declarations" or "declarations" in section:
            rendered.extend(_render_content_blocks([section], references))
        if "content" in section:
            rendered.extend(_render_content_blocks(section.get("content"), references))
    return rendered


def _render_named_sections(sections: Any, references: dict[str, Any]) -> list[str]:
    rendered: list[str] = []
    if not isinstance(sections, list):
        return rendered
    for section in sections:
        if not isinstance(section, dict) or not section.get("content"):
            continue
        title = section.get("title")
        if title:
            rendered.append(f"## {title}")
        rendered.extend(_render_content_blocks(section.get("content"), references))
    return rendered


def _render_content_blocks(blocks: Any, references: dict[str, Any]) -> list[str]:
    rendered: list[str] = []
    if not isinstance(blocks, list):
        return rendered
    for block in blocks:
        if not isinstance(block, dict):
            continue
        rendered.extend(_render_content_block(block, references))
    return rendered


def _render_content_block(block: dict[str, Any], references: dict[str, Any]) -> list[str]:
    block_type = block.get("type")
    block_kind = block.get("kind")
    if block_type == "heading":
        level = min(max(int(block.get("level") or 2), 1), 6)
        text = _collapse_whitespace(str(block.get("text") or ""))
        return [f"{'#' * level} {text}"] if text else []
    if block_type == "paragraph":
        text = _collapse_whitespace(_inline_text(block.get("inlineContent") or block.get("content"), references))
        return [text] if text and text != "![image]" else []
    if block_type in {"unorderedList", "orderedList"}:
        return [_render_list_block(block, references)]
    if block_type in {"codeListing", "codeBlock"} or block_kind == "codeListing":
        return _render_code_block(block)
    if block_kind == "declarations" or "declarations" in block:
        return _render_declarations(block)
    if "content" in block:
        return _render_content_blocks(block.get("content"), references)
    text = _collapse_whitespace(_inline_text(block, references))
    return [text] if text else []


def _render_list_block(block: dict[str, Any], references: dict[str, Any]) -> str:
    block_type = block.get("type")
    lines = []
    for index, item in enumerate(block.get("items") or block.get("content") or [], start=1):
        marker = f"{index}." if block_type == "orderedList" else "-"
        content = item.get("content") if isinstance(item, dict) else item
        text = _collapse_whitespace(_inline_text(content, references))
        if not text and isinstance(item, dict):
            text = _collapse_whitespace(_inline_text(item.get("inlineContent"), references))
        if text:
            lines.append(f"{marker} {text}")
    return "\n".join(lines)


def _render_code_block(block: dict[str, Any]) -> list[str]:
    code = block.get("code") or block.get("syntax") or block.get("content") or ""
    if isinstance(code, list):
        code = "\n".join(_inline_text(item, {}) for item in code)
    code_text = str(code).rstrip()
    if not code_text:
        return []
    syntax = block.get("syntax") or block.get("language") or "swift"
    return [f"```{syntax}\n{code_text}\n```"]


def _render_declarations(block: dict[str, Any]) -> list[str]:
    snippets = []
    for declaration in block.get("declarations") or []:
        if isinstance(declaration, dict):
            text = _fragments_text(declaration.get("tokens"))
            if text:
                snippets.append(text)
    return ["```swift\n" + "\n".join(snippets) + "\n```"] if snippets else []


def _render_identifier_sections(sections: Any, references: dict[str, Any], heading: str) -> list[str]:
    if not isinstance(sections, list) or not sections:
        return []
    rendered = [f"## {heading}"]
    for section in sections:
        if not isinstance(section, dict):
            continue
        title = _collapse_whitespace(str(section.get("title") or section.get("anchor") or "Section"))
        if title:
            rendered.append(f"### {title}")
        lines = [_reference_summary(str(identifier), references) for identifier in section.get("identifiers") or []]
        if lines:
            rendered.append("\n".join(lines))
    return rendered


def _render_reference_index(references: dict[str, Any]) -> list[str]:
    lines = []
    for identifier, reference in list(references.items())[:500]:
        if not isinstance(reference, dict):
            continue
        title = _reference_title(reference, str(identifier))
        abstract = _collapse_whitespace(_inline_text(reference.get("abstract"), references))
        fragments = _fragments_text(reference.get("fragments"))
        details = " ".join(part for part in (fragments, abstract) if part)
        if title or details:
            lines.append(f"- {title}: {details}".strip())
    return ["## Referenced symbols and articles", *lines] if lines else []


def _reference_summary(identifier: str, references: dict[str, Any]) -> str:
    reference = references.get(identifier)
    title = _reference_title(reference, identifier)
    url = _reference_url(reference, identifier)
    abstract = (
        _collapse_whitespace(_inline_text(reference.get("abstract"), references)) if isinstance(reference, dict) else ""
    )
    fragments = _fragments_text(reference.get("fragments")) if isinstance(reference, dict) else ""
    suffix = " — ".join(part for part in (fragments, abstract) if part)
    link = f"[{title}]({url})" if url else title
    return f"- {link} — {suffix}" if suffix else f"- {link}"


def _reference_title(reference: Any, identifier: str) -> str:
    if isinstance(reference, dict):
        for key in ("title", "name"):
            if isinstance(reference.get(key), str) and reference[key].strip():
                return reference[key].strip()
        fragments = _fragments_text(reference.get("fragments") or reference.get("navigatorTitle"))
        if fragments:
            return fragments
    if identifier.startswith(("http://", "https://")):
        return identifier
    return identifier.rsplit("/", 1)[-1]


def _reference_url(reference: Any, identifier: str) -> str:
    if isinstance(reference, dict) and isinstance(reference.get("url"), str):
        url = reference["url"]
        if url.startswith(("http://", "https://")):
            return url
        if url.startswith("/"):
            return f"{APPLE_DEVELOPER_BASE_URL}{url}"
    if identifier.startswith(("http://", "https://")):
        return identifier
    marker = "/documentation/"
    if marker in identifier:
        return f"{APPLE_DEVELOPER_BASE_URL}{marker}{identifier.split(marker, 1)[1]}"
    return identifier


def _inline_text(value: Any, references: dict[str, Any]) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_inline_text(item, references) for item in value)
    if isinstance(value, dict):
        return _inline_dict_text(value, references)
    return str(value)


def _inline_dict_text(value: dict[str, Any], references: dict[str, Any]) -> str:
    item_type = value.get("type")
    if "text" in value and item_type not in {"reference", "image"}:
        text = str(value.get("text", ""))
        return f"`{text}`" if item_type == "codeVoice" else text
    if item_type == "reference":
        return _inline_reference_text(value, references)
    if item_type == "image":
        identifier = str(value.get("identifier") or "image")
        alt = str(value.get("alt") or identifier)
        return f"![{alt}]"
    nested_key = next((key for key in ("inlineContent", "content", "children") if key in value), None)
    if nested_key is not None:
        return _inline_text(value[nested_key], references)
    return str(value["code"]) if "code" in value else ""


def _inline_reference_text(value: dict[str, Any], references: dict[str, Any]) -> str:
    identifier = str(value.get("identifier") or "")
    reference = references.get(identifier) if identifier else None
    title = _reference_title(reference, identifier)
    url = _reference_url(reference, identifier)
    return f"[{title}]({url})" if url else title


def _fragments_text(fragments: Any) -> str:
    if not isinstance(fragments, list):
        return ""
    return "".join(str(part.get("text", "")) for part in fragments if isinstance(part, dict)).strip()


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
