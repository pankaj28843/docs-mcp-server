"""YAML front matter utilities for markdown documents.

Handles parsing and serializing front matter metadata in markdown files.
Uses '-----' delimiters to separate YAML front matter from markdown content.

Example markdown with front matter:
    -----
    url: https://docs.djangoproject.com/en/5.1/intro/tutorial01/
    document_key: a2f3b9c8d1e0...
    indexed_at: 2024-01-15T10:30:00Z
    status: success
    -----
    # Getting Started with Django

    This tutorial begins...
"""

import re
from typing import Any

import yaml


# Front matter delimiter (5 dashes)
DELIMITER = "-----"


def parse_front_matter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML front matter from markdown content.

    Args:
        content: Full markdown content including front matter

    Returns:
        Tuple of (front_matter_dict, markdown_content)
        If no front matter found, returns (empty dict, original content)

    Example:
        >>> content = "-----\\nurl: https://example.com\\n-----\\n# Content"
        >>> metadata, markdown = parse_front_matter(content)
        >>> metadata["url"]
        'https://example.com'
        >>> markdown
        '# Content'
    """
    # Match front matter: starts with -----, YAML content, ends with -----
    pattern = rf"^{re.escape(DELIMITER)}\s*\n(.*?)\n{re.escape(DELIMITER)}\s*\n"
    match = re.match(pattern, content, re.DOTALL)

    if not match:
        # No front matter found
        return {}, content

    yaml_text = match.group(1)
    markdown_content = content[match.end() :]

    try:
        metadata = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        # Invalid YAML - return empty dict
        return {}, content

    # Ensure metadata is a dict
    if not isinstance(metadata, dict):
        return {}, content

    return metadata, markdown_content


def serialize_front_matter(metadata: dict[str, Any], markdown_content: str) -> str:
    """Serialize metadata and content into markdown with front matter.

    Args:
        metadata: Dictionary of metadata to include in front matter
        markdown_content: Markdown content to follow front matter

    Returns:
        Complete markdown document with YAML front matter

    Example:
        >>> meta = {"url": "https://example.com", "status": "success"}
        >>> markdown = "# Hello World"
        >>> serialize_front_matter(meta, markdown)
        '-----\\nstatus: success\\nurl: https://example.com\\n-----\\n# Hello World'

    Note:
        Empty metadata results in markdown-only output (no delimiters)
        YAML is dumped with sorted keys for determinism
    """
    if not metadata:
        # No metadata - return plain markdown
        return markdown_content

    # Sort keys for determinism
    yaml_text = yaml.dump(
        metadata,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=True,
    )

    # Remove trailing newline from YAML (dump adds one)
    yaml_text = yaml_text.rstrip("\n")

    return f"{DELIMITER}\n{yaml_text}\n{DELIMITER}\n{markdown_content}"
