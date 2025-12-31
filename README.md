# docs-mcp-server

**Multi-tenant MCP server for your documentation** — Bring your own docs, index once, search instantly through a unified MCP interface.

[![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://pankaj28843.github.io/docs-mcp-server/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**For**: Developers who want AI assistants (VS Code Copilot, Claude Desktop) to search their documentation instead of hallucinating.

---

## What is it?

A **Model Context Protocol (MCP) server** that lets AI assistants (VS Code Copilot, Claude Desktop) search and fetch documentation from multiple sources through one API. Built with FastMCP, BM25 ranking, and article-extractor.

| Feature | Description |
|---------|-------------|
| 🎯 **Multi-Tenant** | Serve unlimited doc sources from one container |
| 🔍 **Smart Search** | BM25 with IDF floor and length normalization |
| 🔄 **Auto-Sync** | Scheduled crawlers for websites, git syncs for repos |
| 🚀 **MCP Native** | Standard tools (search, fetch, browse) for AI assistants |
| 📚 **Offline-Ready** | Filesystem tenants for local markdown |

---

## Quick Start

**Prerequisites**: Python 3.10+, [uv](https://docs.astral.sh/uv/getting-started/installation/), Docker

```bash
# 1. Clone and install
git clone https://github.com/pankaj28843/docs-mcp-server.git
cd docs-mcp-server
uv sync

# 2. Create configuration (includes 10 sample tenants)
cp deployment.example.json deployment.json

# 3. Deploy to Docker
uv run python deploy_multi_tenant.py --mode online

# 4. Sync a tenant (wait 1-2 min for crawl)
uv run python trigger_all_syncs.py --tenants drf --force

# 5. Test search
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

**Connect VS Code**: Add to `~/.config/Code/User/mcp.json`:
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

> 📖 **Full tutorial**: [Getting Started](https://pankaj28843.github.io/docs-mcp-server/tutorials/getting-started/)

---

## Example Tenants

The included `deployment.example.json` has 10 pre-configured tenants:

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

Add your own by editing `deployment.json`. See [deployment.json Schema](https://pankaj28843.github.io/docs-mcp-server/reference/deployment-json-schema/).

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
