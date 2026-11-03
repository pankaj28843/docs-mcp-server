#!/usr/bin/env python3
"""Refresh a filesystem snapshot of the latest stable Go release notes."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import re

import aiohttp
from lxml import html
import yaml

from .rxjs_api import _create_staging_directory, _publish_snapshot


RELEASES_URL = "https://go.dev/dl/?mode=json"


def latest_release_url(releases: object) -> str:
    """Select the highest stable Go release, ignoring previews and malformed entries."""
    if not isinstance(releases, list):
        raise TypeError("Go release feed must be a list")
    versions = []
    for release in releases:
        if not isinstance(release, dict) or release.get("stable") is not True:
            continue
        match = re.fullmatch(r"go(\d+)\.(\d+)(?:\.(\d+))?", str(release.get("version", "")))
        if match:
            versions.append(tuple(int(part or 0) for part in match.groups()))
    if not versions:
        raise ValueError("Go release feed has no stable versions")
    major, minor, _ = max(versions)
    return f"https://go.dev/doc/go{major}.{minor}"


async def export_snapshot(output_dir: Path) -> str:
    """Fetch and atomically publish one release note, preserving old data on errors."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
        async with session.get(RELEASES_URL) as response:
            response.raise_for_status()
            url = latest_release_url(await response.json())
        async with session.get(url) as response:
            response.raise_for_status()
            document = html.fromstring(await response.text())
    articles = document.xpath("//article")
    if len(articles) != 1:
        raise ValueError("Go release note must contain one article")
    title = document.findtext(".//title")
    body = articles[0].text_content().strip()
    if not title or "Release Notes" not in title or len(body) < 1000:
        raise ValueError("Go release note content is invalid")
    metadata = yaml.safe_dump({"title": title, "url": url}, sort_keys=False)
    staging = _create_staging_directory(output_dir)
    (staging / "release-notes.md").write_text(f"-----\n{metadata}-----\n\n# {title}\n\n{body}\n", encoding="utf-8")
    _publish_snapshot(staging, output_dir)
    return url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(asyncio.run(export_snapshot(args.output_dir)))  # noqa: T201


if __name__ == "__main__":
    main()
