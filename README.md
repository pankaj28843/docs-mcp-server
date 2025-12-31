# docs-mcp-server

**Multi-tenant MCP server for your documentation** - Bring your own docs, index once, search instantly through a unified MCP interface.

[![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://pankaj28843.github.io/docs-mcp-server/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## What is it?

A **Model Context Protocol (MCP) server** that lets AI assistants search and fetch your documentation sources through one API. Built with FastMCP, BM25 ranking, and article-extractor.

**Key Features:**

| Feature | Description |
|---------|-------------|
| 🎯 **Multi-Tenant** | Unlimited doc sources in one container - add any docs you need |
| 🔍 **Smart Search** | BM25 with IDF floor, English preference, length normalization |
| 🔄 **Auto-Sync** | Scheduled crawlers for websites, git syncs for repos |
| 🚀 **MCP Native** | Standard tools (search, fetch, browse) for seamless integration |
| 📚 **Offline-Ready** | Filesystem tenants for local markdown |

---

## Quick Start (3 Commands)

\`\`\`bash
# 1. Clone and install
git clone https://github.com/pankaj28843/docs-mcp-server.git && cd docs-mcp-server && uv sync

# 2. Test with Django docs
uv run python debug_multi_tenant.py --tenant django --test search

# 3. Deploy to Docker (your configured tenants)
uv run python deploy_multi_tenant.py --mode online
\`\`\`

**Result**: MCP server running on \`http://localhost:42042\` with your configured documentation tenants.

---

## Documentation

📚 **[Full Documentation](https://pankaj28843.github.io/docs-mcp-server/)** - Includes:

- **Tutorials**: Getting Started, Adding Tenants, Custom Search
- **How-To Guides**: Git Tenants, Debugging, Docker Deployment
- **Reference**: deployment.json Schema, CLI Commands, MCP Tools
- **Explanations**: Architecture, BM25 Ranking, Sync Strategies

---

## Example Tenants (from deployment.example.json)

The example configuration includes 10 sample tenants to get you started:

**Python**: `django`, `drf`, `fastapi`, `python`, `pytest`  
**AI/Agents**: `aws-bedrock-agentcore`, `strands-sdk`  
**Architecture**: `cosmicpython` (free online)  
**Git-based**: `mkdocs`, `aidlc-rules`

> **Add your own**: Edit `deployment.json` to add any documentation source - websites, git repos, or local markdown files.

[Configuration guide →](https://pankaj28843.github.io/docs-mcp-server/tutorials/adding-first-tenant/)

---

## License

MIT License - See [LICENSE](LICENSE)
