"""Sample data for CI MCP tests - fake docs for all tenant types."""

import json
from pathlib import Path


# Online tenant sample docs with metadata
ONLINE_DOCS = [
    {
        "filename": "getting-started.md",
        "title": "Getting Started",
        "url": "https://webapi.example.com/getting-started/",
        "content": """# Getting Started

WebAPI is a framework for building APIs.

## Installation

```bash
pip install webapi
```

## Quick Example

```python
from webapi import WebAPI

app = WebAPI()

@app.get("/")
def root():
    return {"message": "Hello"}
```
""",
    },
    {
        "filename": "tutorial/routing.md",
        "title": "Routing Tutorial",
        "url": "https://webapi.example.com/tutorial/routing/",
        "content": """# Routing

Define routes in WebAPI.

## Path Parameters

```python
@app.get("/items/{item_id}")
def get_item(item_id: int):
    return {"item_id": item_id}
```

## Query Parameters

```python
@app.get("/search")
def search(q: str, limit: int = 10):
    return {"query": q, "limit": limit}
```
""",
    },
    {
        "filename": "advanced/security.md",
        "title": "Security Guide",
        "url": "https://webapi.example.com/advanced/security/",
        "content": """# Security

Implement authentication and authorization.

## API Keys

```python
from webapi.security import APIKeyHeader

api_key = APIKeyHeader(name="X-API-Key")

@app.get("/protected")
def protected(key: str = Depends(api_key)):
    return {"status": "authenticated"}
```
""",
    },
]

# Git tenant sample docs
GIT_DOCS = [
    {
        "filename": "config.md",
        "content": """# Configuration

Configure your documentation site.

## Basic Config

```yaml
site_name: My Docs
theme: material
```

## Navigation

```yaml
nav:
  - Home: index.md
  - Guide: guide.md
```
""",
    },
    {
        "filename": "themes.md",
        "content": """# Themes

Customize the appearance of your docs.

## Built-in Themes

- material
- readthedocs
- mkdocs

## Custom CSS

```css
.md-header {
    background-color: #2196f3;
}
```
""",
    },
    {
        "filename": "plugins.md",
        "content": """# Plugins

Extend functionality with plugins.

## Search Plugin

Enable full-text search:

```yaml
plugins:
  - search
```

## Git Revision

Show last updated date:

```yaml
plugins:
  - git-revision-date
```
""",
    },
]

# Filesystem tenant sample docs
FILESYSTEM_DOCS = [
    {
        "filename": "index.md",
        "content": """# Local Documentation

Filesystem-based documentation for local access.

## Features

- Fast local access
- No network required
- Version controlled

## Usage

Browse and search docs efficiently.
""",
    },
    {
        "filename": "api/tools.md",
        "content": """# Tools API

Available tools for documentation access.

## Search

```python
results = search("query", tenant="docs")
```

## Fetch

```python
content = fetch("file.md", context="full")
```
""",
    },
    {
        "filename": "api/browse.md",
        "content": """# Browse API

Navigate directory structure.

## Usage

```python
tree = browse("/path", depth=2)
```

## Response

Returns nested tree of files and folders.
""",
    },
]


def create_online_tenant(base_dir: Path, domain: str = "webapi.example.com"):
    """Create online tenant with docs and metadata."""
    docs_dir = base_dir / domain
    meta_dir = base_dir / "__docs_metadata" / domain
    docs_dir.mkdir(parents=True)
    meta_dir.mkdir(parents=True)

    for doc in ONLINE_DOCS:
        # Write markdown
        md_path = docs_dir / doc["filename"]
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(doc["content"])

        # Write metadata
        meta_name = doc["filename"].replace("/", "_").replace(".md", ".meta.json")
        meta_path = meta_dir / meta_name
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps(
                {
                    "url": doc["url"],
                    "title": doc["title"],
                    "metadata": {
                        "markdown_rel_path": f"{domain}/{doc['filename']}",
                        "document_key": doc["filename"].replace("/", "_").replace(".md", ""),
                        "status": "success",
                    },
                },
                indent=2,
            )
        )


def create_git_tenant(base_dir: Path, subpath: str = "docs"):
    """Create git tenant with docs in subpath."""
    docs_dir = base_dir / subpath
    docs_dir.mkdir(parents=True)

    for doc in GIT_DOCS:
        path = docs_dir / doc["filename"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(doc["content"])


def create_filesystem_tenant(base_dir: Path):
    """Create filesystem tenant with plain markdown."""
    base_dir.mkdir(parents=True)

    for doc in FILESYSTEM_DOCS:
        path = base_dir / doc["filename"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(doc["content"])
