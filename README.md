# docs-mcp-server

**Stop AI hallucinations — give your assistant real documentation.**

A Model Context Protocol (MCP) server that provides AI assistants with access to documentation sources through a unified search API. Uses automatic optimization selection (SIMD vectorization, lock-free concurrent access, Bloom filter negative query optimization) for sub-200ms search latency.

[![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://pankaj28843.github.io/docs-mcp-server/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## System Architecture

The server uses a consolidated DocumentationSearchEngine with a clean, simple architecture:

- **Basic search implementation**: Production-ready BM25 scoring with SQLite FTS
- **Deep module design**: Powerful functionality behind simple interface
- **Single responsibility**: Document search and retrieval without complexity
- **Unified interface**: Eliminates interface proliferation and classitis

Each documentation source is indexed using BM25 scoring with configurable boost factors and snippet generation.

## Key Features

| Feature | Description |
|---------|-------------|
| 🎯 **Multi-Tenant** | Serve unlimited documentation sources from one container |
| 🔍 **Optimized Search** | Automatic optimization selection with sub-200ms latency |
| 🔄 **Auto-Sync** | Scheduled crawlers for websites, git syncs for repositories |
| 🚀 **MCP Native** | Standard tools (search, fetch, browse) for AI assistants |
| 📚 **Offline-Ready** | Filesystem tenants for local markdown collections |

---

## Quick Start

Deploy the server and test search functionality:

```bash
# Clone and install dependencies
git clone https://github.com/pankaj28843/docs-mcp-server.git
cd docs-mcp-server
uv sync

# Create configuration with sample documentation sources
cp deployment.example.json deployment.json

# Deploy server container
uv run python deploy_multi_tenant.py --mode online

# Sync documentation source (Django REST Framework example)
uv run python trigger_all_syncs.py --tenants drf --force

# Test search functionality
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

The search test returns ranked results with BM25 scores and generated snippets.

**MCP Integration**: Add to `~/.config/Code/User/mcp.json`:
```json
{
  "servers": {
    "TechDocs": {
      "type": "http", 
      "url": "http://127.0.0.1:42042/mcp"
    }
  }
}
```

**Verification**: Ask VS Code Copilot "Search Django REST Framework docs for serializers" to see results with actual documentation URLs.

---

## Documentation Sources

Pre-configured sources in `deployment.example.json`:

| Codename | Source | Type |
|----------|--------|------|
| `django` | Django framework docs | Online (sitemap) |
| `drf` | Django REST Framework | Online (sitemap) |
| `fastapi` | FastAPI framework | Online (sitemap) |
| `python` | Python stdlib | Online (sitemap) |
| `pytest` | Pytest testing | Online (crawler) |
| `cosmicpython` | Architecture patterns | Online (crawler) |
| `mkdocs` | MkDocs docs | Git (GitHub) |
| `aidlc-rules` | AIDLC workflow rules | Git (GitHub) |

Configure additional sources by editing `deployment.json`. See [deployment.json Schema](https://pankaj28843.github.io/docs-mcp-server/reference/deployment-json-schema/).

---

## Kiro CLI Integration

This project is optimized for Kiro CLI with:

## Kiro CLI Integration

This project is optimized for Kiro CLI with:

- **Maximally permissive execution** - All tools auto-approved in safe VM environment
- **Validation hooks** - Auto-format on write, full validation on completion
- **Skills integration** - Common tasks available via `/skill` command
- **Cross-agent alignment** - Consistent behavior across Kiro, GitHub Copilot, and Gemini CLI

### Quick Commands

```bash
# Activate the agent
kiro-cli chat docs-mcp-dev

# Use skills for common tasks
/skill validate-code    # Full validation loop
/skill quick-test      # Unit tests with coverage  
/skill format-code     # Format and lint
/skill build-docs      # Build documentation
/skill deploy-local    # Deploy server locally
```

### Git Hooks

Pre-commit hooks automatically format code:
```bash
# Install pre-commit hooks
pre-commit install
```

Pre-push hooks run tests with coverage requirements before pushing.

---

## Documentation

| Section | Description |
|---------|-------------|
| 📚 [Tutorials](https://pankaj28843.github.io/docs-mcp-server/tutorials/getting-started/) | Step-by-step guides for new users |
| 🛠️ [How-To Guides](https://pankaj28843.github.io/docs-mcp-server/how-to/configure-git-tenant/) | Solve specific tasks |
| 📖 [Reference](https://pankaj28843.github.io/docs-mcp-server/reference/deployment-json-schema/) | Configuration schema, CLI, API |
| 💡 [Explanations](https://pankaj28843.github.io/docs-mcp-server/explanations/architecture/) | Architecture, design decisions |

---

## Contributing

See [Contributing Guide](https://pankaj28843.github.io/docs-mcp-server/contributing/) for development setup and guidelines.

---

## License

MIT License — See [LICENSE](LICENSE)
