"""Path builder for deterministic URL-to-filesystem mapping.

Converts URLs to human-readable nested folder structures with YAML front matter.
Replaces SHA-256 hashed filenames with semantic paths.

Following the plan from craweled-data-improvement-plan.md:
- Deterministic path generation from canonical URLs
- Normalized segments for filesystem safety
- Mirrored metadata directory structure
- Query string handling (configurable)

Design Philosophy:
- Same URL → Same path (deterministic)
- Paths mirror URL structure (human-readable)
- Cross-platform compatible (path length limits, forbidden chars)
- Git-friendly (meaningful diffs, no hash collisions)
"""

import hashlib
from pathlib import Path
import re
from typing import ClassVar
from urllib.parse import parse_qsl, unquote, urldefrag, urlencode, urlparse, urlunparse


class PathBuilder:
    """Build deterministic filesystem paths from URLs.

    Handles URL normalization, segment sanitization, and metadata mirroring.
    """

    # Constants from plan
    MAX_PATH_LENGTH = 200
    MAX_SEGMENT_LENGTH = 100
    MAX_QUERY_SUFFIX_LENGTH = 80
    METADATA_DIR = "__docs_metadata"

    # File extensions that should be preserved in filename
    FILE_EXTENSIONS: ClassVar[set[str]] = {
        ".html",
        ".htm",
        ".pdf",
        ".txt",
        ".xml",
        ".json",
        ".yaml",
        ".yml",
        ".md",
        ".rst",
    }

    def __init__(self, *, ignore_query_strings: bool = True):
        """Initialize path builder.

        Args:
            ignore_query_strings: If True, strip query strings from URLs.
                                 Most docs sites use them for tracking only.
        """
        self.ignore_query_strings = ignore_query_strings

    def canonicalize_url(self, url: str) -> str:
        """Normalize URL to canonical form for deterministic path generation.

        Steps:
        1. Remove fragments (#section)
        2. Lowercase domain
        3. Normalize path (add trailing slash for directories)
        4. Sort query params (or remove if ignore_query_strings=True)

        Args:
            url: Raw URL string

        Returns:
            Canonical URL string

        Examples:
            >>> pb = PathBuilder()
            >>> pb.canonicalize_url("https://Docs.Example.com/Page#section")
            'https://docs.example.com/page/'
            >>> pb.canonicalize_url("https://docs.example.com/guide.html")
            'https://docs.example.com/guide.html'
        """
        # Remove fragment
        url_without_fragment, _ = urldefrag(url)

        # Parse components
        parsed = urlparse(url_without_fragment)
        scheme, netloc, path, params, query, _ = parsed

        # Lowercase domain
        netloc = netloc.lower()

        # Normalize path
        if not path:
            path = "/"
        elif not self._has_file_extension(path) and not path.endswith("/"):
            # Directory URL without trailing slash - add it
            path = path + "/"

        # Handle query string
        if query:
            query = "" if self.ignore_query_strings else urlencode(sorted(parse_qsl(query)))

        # Reconstruct canonical URL
        canonical = urlunparse((scheme, netloc, path, params, query, ""))
        return canonical

    def build_markdown_path(self, url: str, *, relative_to: Path | None = None) -> Path:
        """Build markdown file path from URL.

        Generates human-readable nested directory structure mirroring URL.

        Args:
            url: URL to convert
            relative_to: Optional base path (if None, returns relative path)

        Returns:
            Path to markdown file

        Examples:
            >>> pb = PathBuilder()
            >>> pb.build_markdown_path("https://docs.djangoproject.com/en/5.2/intro/tutorial01/")
            Path('docs.djangoproject.com/en/5.2/intro/tutorial01.md')
            >>> pb.build_markdown_path("https://docs.python.org/3/library/asyncio.html")
            Path('docs.python.org/3/library/asyncio.html.md')
        """
        canonical = self.canonicalize_url(url)
        parsed = urlparse(canonical)

        # Domain becomes top-level directory
        domain = parsed.netloc.lower()

        query_suffix = ""
        if parsed.query and not self.ignore_query_strings:
            query_suffix = self._build_query_suffix(parsed.query)

        # Split path into segments
        path_parts = [p for p in parsed.path.split("/") if p]

        # Determine filename and directory structure
        if not path_parts:
            # Root URL: https://example.com/
            filename = "index.md"
            dir_parts = [domain]
        elif self._has_file_extension(path_parts[-1]):
            # URL ends with file extension: .../file.html
            filename = path_parts[-1] + ".md"
            dir_parts = [domain, *path_parts[:-1]]
        elif parsed.path.endswith("/"):
            # Trailing slash: .../tutorial01/
            filename = path_parts[-1] + ".md" if path_parts else "index.md"
            dir_parts = [domain, *path_parts[:-1]] if path_parts else [domain]
        else:
            # Terminal segment without extension: .../tutorial01
            filename = path_parts[-1] + ".md"
            dir_parts = [domain, *path_parts[:-1]]

        # Normalize all segments
        normalized_parts = [self._normalize_segment(p) for p in dir_parts]

        # Build path
        directory = Path(*normalized_parts) if normalized_parts else Path()

        filename = self._apply_query_suffix(filename, query_suffix)

        rel_path = directory / filename

        # Handle path length limits
        if len(str(rel_path)) > self.MAX_PATH_LENGTH:
            rel_path = self._truncate_path(rel_path, filename)

        # Make absolute if base path provided
        if relative_to:
            return relative_to / rel_path

        return rel_path

    def build_metadata_path(self, markdown_path: Path, *, relative_to: Path | None = None) -> Path:
        """Build metadata file path mirroring markdown structure.

        Args:
            markdown_path: Path to markdown file (relative or absolute)
            relative_to: Optional base path (if None, returns relative path)

        Returns:
            Path to metadata .meta.json file

        Examples:
            >>> pb = PathBuilder()
            >>> md = Path("docs.djangoproject.com/en/5.2/intro/tutorial01.md")
            >>> pb.build_metadata_path(md)
            Path('__docs_metadata/docs.djangoproject.com/en/5.2/intro/tutorial01.meta.json')
        """
        # If markdown_path is absolute, make it relative to relative_to
        if markdown_path.is_absolute() and relative_to:
            try:
                markdown_path = markdown_path.relative_to(relative_to)
            except ValueError:
                # Not relative to base - use as-is
                pass

        # Replace extension with .meta.json
        metadata_rel = self.METADATA_DIR / markdown_path.with_suffix(".meta.json")

        if relative_to:
            return relative_to / metadata_rel

        return metadata_rel

    def _build_query_suffix(self, query: str) -> str:
        """Encode query parameters into filename-safe suffix."""

        components = self._normalized_query_components(query)
        if not components:
            return ""

        suffix = "__q__" + "__".join(components)
        if len(suffix) <= self.MAX_QUERY_SUFFIX_LENGTH:
            return suffix

        digest = hashlib.sha256("__".join(components).encode()).hexdigest()[:12]
        return f"__q__hash_{digest}"

    def _apply_query_suffix(self, filename: str, suffix: str) -> str:
        """Append suffix before the .md extension when provided."""

        if not suffix:
            return filename

        if not filename.endswith(".md"):
            return f"{filename}{suffix}"

        stem = filename[:-3]
        return f"{stem}{suffix}.md"

    def _normalized_query_components(self, query: str) -> list[str]:
        """Return normalized key/value components for a query string."""

        params = sorted(parse_qsl(query, keep_blank_values=True))
        components: list[str] = []
        for key, value in params:
            key_segment = self._normalize_segment(key) or "param"
            if value:
                value_segment = self._normalize_segment(value) or "value"
                components.append(f"{key_segment}_{value_segment}")
            else:
                components.append(key_segment)
        return components

    def _normalize_segment(self, segment: str) -> str:
        """Normalize URL segment to filesystem-safe name.

        Rules:
        - Lowercase
        - Replace spaces with hyphens
        - Remove/replace forbidden characters
        - Decode percent-encoding
        - Truncate to MAX_SEGMENT_LENGTH

        Args:
            segment: Raw URL segment

        Returns:
            Normalized segment safe for filesystem
        """
        # Decode percent-encoding
        segment = unquote(segment)

        # Lowercase
        segment = segment.lower()

        # Replace spaces with hyphens
        segment = segment.replace(" ", "-")

        # Remove forbidden characters (keep alphanumeric, dash, underscore, dot)
        segment = re.sub(r"[^a-z0-9._-]", "_", segment)

        # Remove multiple consecutive underscores/dashes
        segment = re.sub(r"[-_]+", "-", segment)

        # Trim leading/trailing dashes
        segment = segment.strip("-_.")

        # Truncate if too long
        if len(segment) > self.MAX_SEGMENT_LENGTH:
            # Keep first part + hash of overflow
            overflow = segment[self.MAX_SEGMENT_LENGTH :]
            hash_suffix = hashlib.sha256(overflow.encode()).hexdigest()[:8]
            segment = segment[: self.MAX_SEGMENT_LENGTH - 9] + "-" + hash_suffix

        return segment or "index"

    def _has_file_extension(self, path_segment: str) -> bool:
        """Check if path segment has a known file extension.

        Args:
            path_segment: Last part of URL path

        Returns:
            True if segment ends with known file extension
        """
        lower = path_segment.lower()
        return any(lower.endswith(ext) for ext in self.FILE_EXTENSIONS)

    def _truncate_path(self, path: Path, filename: str) -> Path:
        """Truncate path to fit within MAX_PATH_LENGTH.

        Strategy: Keep domain + filename, hash middle segments.

        Args:
            path: Original path that's too long
            filename: Filename to preserve

        Returns:
            Truncated path
        """
        parts = list(path.parts)

        if len(parts) <= 2:
            # Can't truncate further - just hash entire path
            path_str = str(path)
            hash_suffix = hashlib.sha256(path_str.encode()).hexdigest()[:16]
            return Path(f"truncated-{hash_suffix}") / filename

        # Keep domain (first part) and filename
        domain = parts[0]
        middle_parts = parts[1:-1] if len(parts) > 2 else []

        # Hash middle segments
        middle_str = "/".join(middle_parts)
        middle_hash = hashlib.sha256(middle_str.encode()).hexdigest()[:16]

        return Path(domain) / middle_hash / filename
