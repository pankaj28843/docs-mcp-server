#!/usr/bin/env python3
"""Export the public RxJS API manifest and generated pages as a filesystem tenant.

The RxJS site serves JavaScript shells to ordinary crawlers. Its generated
``api-list.json`` is the reference viewer's public API inventory; each listed
item and module has a corresponding generated JSON page with rendered HTML.
This script fails the entire snapshot if any page or version check fails.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
import ctypes
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

import aiohttp
from lxml import html
import yaml


BASE_URL = "https://rxjs.dev"
MANIFEST_PATH = "api/api-list.json"
SOURCE_TAG_RE = re.compile(r"github\.com/reactivex/rxjs/tree/([^/]+)/", re.I)
BLOCK_TAGS = frozenset(
    {
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dt",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)


def api_paths(manifest: object) -> tuple[str, ...]:
    """Return every public item plus its module page from the official list."""
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("RxJS API manifest must contain modules")
    paths: set[str] = set()
    for module in manifest:
        if not isinstance(module, Mapping) or not isinstance(module.get("title"), str):
            raise TypeError("RxJS API manifest contains an invalid module")
        module_path = f"api/{module['title']}"
        if not re.fullmatch(r"api/[A-Za-z0-9_-]+", module_path):
            raise ValueError(f"Invalid RxJS module path: {module_path}")
        paths.add(module_path)
        items = module.get("items")
        if not isinstance(items, list):
            raise TypeError(f"RxJS module has no API inventory: {module_path}")
        for item in items:
            if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
                raise TypeError(f"Invalid RxJS API item in {module_path}")
            path = item["path"]
            if not re.fullmatch(r"api/[A-Za-z0-9_/-]+", path) or "//" in path or "/../" in path:
                raise ValueError(f"Invalid RxJS API path: {path}")
            if path in paths:
                raise ValueError(f"Duplicate RxJS API path: {path}")
            paths.add(path)
    return tuple(sorted(paths))


def render_page(path: str, page: object, expected_version: str, captured_at: str) -> str:
    """Render a generated API page with its canonical URL and source tag."""
    if not isinstance(page, Mapping) or page.get("id") != path:
        raise ValueError(f"RxJS API payload ID mismatch for {path}")
    title, contents = page.get("title"), page.get("contents")
    if not isinstance(title, str) or not title or not isinstance(contents, str) or not contents:
        raise ValueError(f"RxJS API payload is empty: {path}")
    versions = set(SOURCE_TAG_RE.findall(contents))
    if versions != {expected_version}:
        raise ValueError(f"RxJS API source version mismatch for {path}: {sorted(versions)}")

    tree = html.fragment_fromstring(contents, create_parent="div")
    for node in tree.xpath(
        ".//script|.//style|.//*[contains(concat(' ', normalize-space(@class), ' '), ' page-actions ')]"
    ):
        node.drop_tree()
    for node in tree.iter():
        if isinstance(node.tag, str) and node.tag.lower() in BLOCK_TAGS:
            node.tail = "\n" + (node.tail or "")
            if node.text:
                node.text = "\n" + node.text
    body = re.sub(r"\n{3,}", "\n\n", tree.text_content()).strip()
    if len(body) < 50:
        raise ValueError(f"RxJS API rendered body is too short: {path}")
    metadata = {
        "title": title,
        "url": f"{BASE_URL}/{path}",
        "source_json_url": f"{BASE_URL}/generated/docs/{path}.json",
        "source_version": expected_version,
        "source_repository": "https://github.com/ReactiveX/rxjs",
        "captured_at": captured_at,
    }
    return f"-----\n{yaml.safe_dump(metadata, sort_keys=False)}-----\n\n# {title}\n\n{body}\n"


def _exchange_directories(staging: Path, output_dir: Path) -> None:
    """Atomically swap populated directories on Linux without an empty window."""
    renameat2 = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if renameat2 is None:
        raise RuntimeError("Atomic RxJS snapshot replacement requires Linux renameat2")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(staging), -100, os.fsencode(output_dir), 2) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(output_dir))


def _publish_snapshot(staging: Path, output_dir: Path) -> None:
    """Publish once, preserving the old snapshot if promotion fails."""
    try:
        if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
            raise ValueError(f"Snapshot destination is not a directory: {output_dir}")
        if output_dir.exists():
            _exchange_directories(staging, output_dir)
        else:
            staging.rename(output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _create_staging_directory(output_dir: Path) -> Path:
    """Keep uncommitted pages outside the tenant's indexable docs root."""
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f".{output_dir.parent.name}-{output_dir.name}-", dir=output_dir.parent.parent))


async def export_snapshot(output_dir: Path, expected_version: str, concurrency: int = 8) -> int:
    """Fetch and validate the complete public API before replacing the snapshot."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", expected_version):
        raise ValueError("Expected version must be an exact semver release")
    timeout = aiohttp.ClientTimeout(total=45)
    connector = aiohttp.TCPConnector(limit=concurrency, limit_per_host=concurrency)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        async with session.get(f"{BASE_URL}/generated/docs/{MANIFEST_PATH}") as response:
            response.raise_for_status()
            paths = api_paths(await response.json())

        semaphore = asyncio.Semaphore(concurrency)
        captured_at = datetime.now(UTC).isoformat()

        async def fetch(path: str) -> tuple[str, str]:
            async with semaphore, session.get(f"{BASE_URL}/generated/docs/{path}.json") as response:
                response.raise_for_status()
                return path, render_page(path, await response.json(), expected_version, captured_at)

        pages = await asyncio.gather(*(fetch(path) for path in paths))

    staging = _create_staging_directory(output_dir)
    try:
        for path, markdown in pages:
            destination = staging / f"{path}.md"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(markdown, encoding="utf-8")
        (staging / "snapshot-manifest.json").write_text(
            json.dumps(
                {
                    "source_api_manifest_url": f"{BASE_URL}/generated/docs/{MANIFEST_PATH}",
                    "source_version": expected_version,
                    "captured_at": captured_at,
                    "document_count": len(paths),
                    "paths": list(paths),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        _publish_snapshot(staging, output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return len(pages)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-version", required=True, help="Exact published RxJS source tag, e.g. 7.8.2")
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("--concurrency must be positive")
    count = asyncio.run(export_snapshot(args.output_dir, args.expected_version, args.concurrency))
    sys.stdout.write(f"Exported {count} RxJS {args.expected_version} API pages to {args.output_dir}\n")


if __name__ == "__main__":
    main()
