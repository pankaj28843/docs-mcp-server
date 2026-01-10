# docs-mcp-server

**Stop AI hallucinations — give your assistant real documentation.**

A Model Context Protocol (MCP) server that lets VS Code Copilot, Claude Desktop, and other AI assistants search your documentation sources (Django, FastAPI, internal docs) through one unified API. No more "I think the syntax is..." — your assistant cites actual docs.

[![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://pankaj28843.github.io/docs-mcp-server/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Who Is This For?

**Audience**: Developers using AI assistants who want grounded answers from real documentation.

**Prerequisites**: Python 3.10+, `uv`, and Docker for deployment workflows.

**Time**: ~10 minutes to run the quick start, longer for multi-tenant setup.

**What you'll learn**: How to deploy, sync, index, and query docs through MCP tools.

**What You DON'T Need**:
- Deep MCP protocol knowledge (handled by the server)
- Custom search infrastructure (BM25 included)
- Web scraping expertise (crawlers built-in)

## Key Features

| Feature | Description |
|---------|-------------|
| 🎯 **Multi-Tenant** | Serve unlimited doc sources from one container |
| 🔍 **Smart Search** | BM25 with IDF floor — works for 7 docs or 2500 docs |
| 🔄 **Auto-Sync** | Scheduled crawlers for websites, git syncs for repos |
| 🚀 **MCP Native** | Standard tools (search, fetch, browse) for AI assistants |
| 📚 **Offline-Ready** | Filesystem tenants for local markdown |

---

## Quick Start

**Time**: ~10 minutes  
**What you'll achieve**: Deploy the server, sync documentation, and test search from VS Code Copilot.

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

# Expected: You should see ranked search results with scores and snippets

> 🔎 **Need match-trace data?** Set `infrastructure.search_include_stats` to `true` in `deployment.json` to emit `match_stage`, `match_reason`, and ripgrep flag metadata (plus timing stats) for every search. Clients can no longer toggle diagnostics per request—only infra owners control this knob.
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

**Verify**: Reload VS Code, open Copilot chat, and ask "Search Django REST Framework docs for serializers." You should see results citing actual DRF documentation URLs.

> 📖 **Full tutorial**: [Getting Started](https://pankaj28843.github.io/docs-mcp-server/tutorials/getting-started/)

---

## Included Documentation Sources

Pre-configured tenants in `deployment.example.json` — copy, edit, and add your own:

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
