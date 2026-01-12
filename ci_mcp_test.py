#!/usr/bin/env python3
"""
CI MCP Tools Test Script

Creates realistic test data for different tenant types and validates all MCP tools.
"""

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List


def create_test_deployment_config() -> Dict:
    """Create deployment config with realistic tenant types."""
    return {
        "infrastructure": {
            "mcp_host": "0.0.0.0",
            "mcp_port": 42042,
            "default_client_model": "claude-haiku-4.5",
            "max_concurrent_requests": 20,
            "uvicorn_workers": 1,
            "uvicorn_limit_concurrency": 200,
            "log_level": "info",
            "operation_mode": "online",
            "http_timeout": 120,
            "search_timeout": 30,
            "search_include_stats": True,
            "default_fetch_mode": "surrounding",
            "default_fetch_surrounding_chars": 1000,
            "crawler_playwright_first": True,
            "article_extractor_fallback": {"enabled": False}
        },
        "tenants": [
            {
                "source_type": "online",
                "codename": "fastapi-ci",
                "docs_name": "FastAPI CI Test",
                "docs_sitemap_url": "https://fastapi.tiangolo.com/sitemap.xml",
                "url_whitelist_prefixes": "https://fastapi.tiangolo.com/",
                "enable_crawler": False,
                "docs_root_dir": "./ci-mcp-data/fastapi-ci",
                "refresh_schedule": "0 3 * * *",
                "test_queries": {
                    "natural": ["FastAPI routes", "FastAPI models"],
                    "phrases": ["route", "model"],
                    "words": ["fastapi"]
                }
            },
            {
                "source_type": "git",
                "codename": "mkdocs-ci",
                "docs_name": "MkDocs CI Test",
                "git_repo_url": "https://github.com/mkdocs/mkdocs.git",
                "git_branch": "master",
                "git_subpaths": ["docs"],
                "docs_root_dir": "./ci-mcp-data/mkdocs-ci",
                "refresh_schedule": "0 4 * * *",
                "test_queries": {
                    "natural": ["MkDocs configuration", "MkDocs themes"],
                    "phrases": ["config", "theme"],
                    "words": ["mkdocs"]
                }
            },
            {
                "source_type": "filesystem",
                "codename": "local-ci",
                "docs_name": "Local Filesystem CI Test",
                "docs_root_dir": "./ci-mcp-data/local-ci",
                "test_queries": {
                    "natural": ["MCP tools", "search functionality"],
                    "phrases": ["search", "browse"],
                    "words": ["mcp", "tools"]
                }
            }
        ]
    }


def create_online_test_data(tenant_dir: Path):
    """Create realistic online tenant test data."""
    # Simulate crawled FastAPI docs
    docs = [
        ("tutorial/first-steps.md", """# First Steps

FastAPI is a modern, fast (high-performance), web framework for building APIs with Python 3.7+ based on standard Python type hints.

## Key Features

- **Fast**: Very high performance, on par with NodeJS and Go
- **Fast to code**: Increase the speed to develop features by about 200% to 300%
- **Fewer bugs**: Reduce about 40% of human (developer) induced errors
- **Intuitive**: Great editor support. Completion everywhere. Less time debugging
- **Easy**: Designed to be easy to use and learn. Less time reading docs
- **Short**: Minimize code duplication. Multiple features from each parameter declaration
- **Robust**: Get production-ready code. With automatic interactive documentation

## Installation

```bash
pip install fastapi
pip install "uvicorn[standard]"
```

## Example

Create a file `main.py` with:

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"Hello": "World"}
```

Run the server with:

```bash
uvicorn main:app --reload
```
"""),
        ("tutorial/path-parameters.md", """# Path Parameters

You can declare path "parameters" or "variables" with the same syntax used by Python format strings:

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/items/{item_id}")
def read_item(item_id: int, q: str = None):
    return {"item_id": item_id, "q": q}
```

The value of the path parameter `item_id` will be passed to your function as the argument `item_id`.

## Path Parameters with Types

You can declare the type of a path parameter in the function, using standard Python type annotations:

```python
@app.get("/items/{item_id}")
def read_item(item_id: int):
    return {"item_id": item_id}
```

In this case, `item_id` is declared to be an `int`.

This will give you editor support inside of your function, with error checks, completion, etc.
"""),
        ("advanced/security.md", """# Security

FastAPI provides several tools to help you deal with security easily, rapidly, in a standard way, without having to study and learn all the security specifications.

## OAuth2 with Password (and hashing), Bearer with JWT tokens

OAuth2 is a specification that defines several ways to handle authentication and authorization.

It is quite an extensive specification and covers several complex use cases.

It includes ways to authenticate using a "third party".

That's what all the systems with "login with Facebook, Google, Twitter, GitHub" use underneath.

## OAuth2 with Password and Bearer

OAuth2 specifies that when using the "password flow" (that we are using) the client/user must send a `username` and `password` fields as form data.

And the specification says that the fields have to be named like that. So `user-name` or `email` wouldn't work.

But don't worry, you can show it as you wish to your end users in the frontend.

And your database models can use any other names you want.

But for the login endpoint, we need to use these names to be compatible with the specification (and be able to, for example, use the integrated API documentation system).
""")
    ]
    
    for filename, content in docs:
        file_path = tenant_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)


def create_git_test_data(tenant_dir: Path):
    """Create realistic git tenant test data."""
    # Simulate cloned MkDocs docs
    docs = [
        ("user-guide/configuration.md", """# Configuration

MkDocs is configured with a YAML configuration file in your docs directory, typically named `mkdocs.yml`.

## Minimal Configuration

The minimum required configuration is:

```yaml
site_name: My Docs
```

## Full Configuration

A more complete configuration might look like:

```yaml
site_name: My Docs
site_url: https://example.com/
nav:
    - Home: index.md
    - About: about.md
theme: readthedocs
```

## Configuration Options

### site_name

This is the name of your documentation site and will be used in the navigation bar and page titles.

### site_url

The full URL to your site. This will be added to the generated HTML.

### nav

This setting is used to determine the format and layout of the global navigation for the site.

### theme

Sets the theme of your documentation site. MkDocs includes a few built-in themes.
"""),
        ("user-guide/writing-your-docs.md", """# Writing Your Docs

MkDocs pages must be authored in Markdown. MkDocs uses the Python-Markdown library to render Markdown documents to HTML.

## File Layout

Your documentation source should be written as regular Markdown files, and placed in a directory somewhere in your project.

Typically this directory will be named `docs` and will exist at the top level of your project, alongside the `mkdocs.yml` configuration file.

```
mkdocs.yml    # The configuration file.
docs/
    index.md  # The documentation homepage.
    ...       # Other markdown pages, images and other files.
```

## Index Pages

When MkDocs builds your site, it will create an `index.html` file for each Markdown file in your docs directory.

If a directory contains an `index.md` file, that file will be used to generate the `index.html` file for that directory.

## Linking to Pages

MkDocs allows you to interlink your documentation by using regular Markdown linking syntax.

```markdown
Please see the [project license](license.md) for further details.
```
"""),
        ("dev-guide/themes.md", """# Themes

A guide to creating and distributing custom themes.

## Creating a Custom Theme

The bare minimum required for a custom theme is a single template file which defines the layout for all pages.

This template file should be named `main.html` and placed in a directory which will be the theme directory.

## Template Variables

Each template in a theme is built with the Jinja2 template engine. A number of global variables are available to all templates.

### config

The `config` variable is an instance of MkDocs' config object and is how you can access any configuration option set in `mkdocs.yml`.

### page

The `page` variable contains the metadata and content for the current page being rendered.

### nav

The `nav` variable is the site navigation object and can be used to create the site navigation.

## Packaging Themes

Themes can be packaged and distributed as Python packages. This allows themes to be easily installed and shared.

To package a theme, create a Python package with the theme files in a subdirectory.
""")
    ]
    
    for filename, content in docs:
        file_path = tenant_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)


def create_filesystem_test_data(tenant_dir: Path):
    """Create realistic filesystem tenant test data."""
    docs = [
        ("getting-started/index.md", """# Getting Started with MCP Tools

The Model Context Protocol (MCP) provides a standardized way for AI assistants to access external data sources and tools.

## What is MCP?

MCP is an open protocol that enables secure, controlled interactions between AI systems and external resources like databases, APIs, and file systems.

## Key Features

- **Standardized Interface**: Consistent API across different data sources
- **Security**: Built-in authentication and authorization
- **Extensibility**: Easy to add new tools and data sources
- **Performance**: Optimized for real-time AI interactions

## Installation

```bash
pip install mcp-tools
```

## Basic Usage

```python
from mcp_tools import Client

client = Client()
results = client.search("documentation")
```

This will search across all configured MCP data sources and return relevant results.
"""),
        ("user-guide/search.md", """# Search Functionality

The MCP search system provides powerful full-text search capabilities across all your documentation sources.

## Search Features

### Full-Text Search

Search across all document content with relevance scoring:

```python
results = client.search("configuration settings")
```

### Filtered Search

Search within specific tenants or document types:

```python
results = client.search("API", tenant="fastapi-docs")
```

### Advanced Queries

Use boolean operators and field-specific searches:

```python
results = client.search("title:configuration AND content:yaml")
```

## Search Configuration

Configure search behavior in your deployment:

```yaml
search_timeout: 30
search_include_stats: true
default_fetch_mode: "surrounding"
```

## Performance Tips

- Use specific terms rather than generic words
- Combine multiple search terms for better results
- Use tenant filtering for faster searches
- Enable search statistics for debugging
"""),
        ("api-reference/tools.md", """# MCP Tools API Reference

Complete reference for all available MCP tools.

## Core Tools

### list_tenants()

Lists all available documentation tenants.

**Returns:** List of tenant metadata

**Example:**
```python
tenants = client.list_tenants()
for tenant in tenants:
    print(f"{tenant.codename}: {tenant.display_name}")
```

### describe_tenant(codename: str)

Get detailed information about a specific tenant.

**Parameters:**
- `codename`: Tenant identifier

**Returns:** Tenant configuration and metadata

### root_search(tenant: str, query: str, **kwargs)

Search within a specific tenant.

**Parameters:**
- `tenant`: Target tenant codename
- `query`: Search query string
- `size`: Maximum results (default: 10)
- `word_match`: Enable whole word matching

**Returns:** Search results with scores and snippets

### root_fetch(tenant: str, uri: str, context: str)

Fetch document content by URI.

**Parameters:**
- `tenant`: Target tenant codename
- `uri`: Document URI (supports file:// and http://)
- `context`: Context mode ("full" or "surrounding")

**Returns:** Document content and metadata

### root_browse(tenant: str, path: str, depth: int)

Browse directory structure for filesystem tenants.

**Parameters:**
- `tenant`: Target tenant codename
- `path`: Directory path (empty for root)
- `depth`: Maximum traversal depth

**Returns:** Directory tree structure
""")
    ]
    
    for filename, content in docs:
        file_path = tenant_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)


async def run_mcp_tests(config_path: str) -> bool:
    """Run comprehensive MCP tools tests."""
    import subprocess
    
    tests = [
        ("list_tenants", ["--root-test", "list"]),
        ("describe_tenant", ["--root-test", "describe", "--target-tenant", "local-ci"]),
        ("browse", ["--root-test", "browse", "--target-tenant", "local-ci"]),
        ("search", ["--root-test", "search", "--target-tenant", "local-ci"])
    ]
    
    print("🚀 Running MCP Tools Integration Tests")
    
    # Build search index for filesystem tenant
    print("📚 Building search index...")
    index_cmd = [
        "uv", "run", "python", "trigger_all_indexing.py",
        "--config", config_path,
        "--tenants", "local-ci"
    ]
    
    try:
        result = subprocess.run(index_cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"❌ Index build failed: {result.stderr}")
            return False
        print("✅ Search index built successfully")
    except subprocess.TimeoutExpired:
        print("❌ Index build timed out")
        return False
    
    # Run MCP tool tests
    all_passed = True
    for test_name, test_args in tests:
        print(f"🔍 Testing {test_name}...")
        
        cmd = [
            "uv", "run", "python", "debug_multi_tenant.py",
            "--config", config_path,
            "--root"
        ] + test_args
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                print(f"✅ {test_name}: PASSED")
            else:
                print(f"❌ {test_name}: FAILED")
                print(f"   Error: {result.stderr[-200:] if result.stderr else 'No error output'}")
                all_passed = False
        except subprocess.TimeoutExpired:
            print(f"❌ {test_name}: TIMEOUT")
            all_passed = False
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
            all_passed = False
    
    return all_passed


async def main():
    """Main CI test function."""
    print("🏗️  Setting up CI test environment...")
    
    # Create test data directory
    test_data_dir = Path("./ci-mcp-data")
    if test_data_dir.exists():
        shutil.rmtree(test_data_dir)
    test_data_dir.mkdir()
    
    # Create tenant directories and test data
    tenants = {
        "fastapi-ci": create_online_test_data,
        "mkdocs-ci": create_git_test_data,
        "local-ci": create_filesystem_test_data
    }
    
    for tenant_name, create_func in tenants.items():
        tenant_dir = test_data_dir / tenant_name
        tenant_dir.mkdir()
        create_func(tenant_dir)
        print(f"📁 Created test data for {tenant_name}")
    
    # Create deployment config
    config = create_test_deployment_config()
    config_path = "deployment.ci-test.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"⚙️  Created deployment config: {config_path}")
    
    # Run tests
    success = await run_mcp_tests(config_path)
    
    # Cleanup
    shutil.rmtree(test_data_dir)
    os.remove(config_path)
    
    if success:
        print("\n✅ All MCP tools tests passed!")
        return 0
    else:
        print("\n❌ Some MCP tools tests failed!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
