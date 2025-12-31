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

## Prerequisites

- **Python 3.10+**
- **uv** (Fast Python package installer) - [Install uv](https://docs.astral.sh/uv/getting-started/installation/)
- **Docker** (for deployment)

---

## Quick Start (Fresh Clone)

Follow these steps in order to get up and running:

### Step 1: Clone and Install

```bash
git clone https://github.com/pankaj28843/docs-mcp-server.git
cd docs-mcp-server
uv sync
```

### Step 2: Create Your Configuration

Copy the example configuration to create your own `deployment.json`:

```bash
cp deployment.example.json deployment.json
```

The example includes 10 pre-configured documentation tenants. You can use them as-is or edit `deployment.json` to customize.

### Step 3: Deploy to Docker

```bash
uv run python deploy_multi_tenant.py --mode online
```

This builds and starts the MCP server container on port 42042.

### Step 4: Trigger Initial Sync

After deployment, trigger a sync to crawl documentation. Start with a small tenant like `drf` (Django REST Framework):

```bash
uv run python trigger_all_syncs.py --tenants drf --force
```

**Wait 1-2 minutes** for the sync to complete. Check status:

```bash
curl -s http://localhost:42042/drf/sync/status | jq .
```

### Step 5: Test Search

Once sync completes, test that search works:

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

**Expected output:**
```
✅ Search successful, returned 5 results
```

### Step 6: Connect VS Code

Add the MCP server to your VS Code configuration (`~/.config/Code/User/mcp.json` on Linux):

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

Now your AI assistant (Copilot, Claude, etc.) can search all your configured documentation tenants.

---

## Example Tenants (from deployment.example.json)

The example configuration includes 10 sample tenants to get you started:

| Category | Tenants |
|----------|---------|
| **Python** | `django`, `drf`, `fastapi`, `python`, `pytest` |
| **AI/Agents** | `aws-bedrock-agentcore`, `strands-sdk` |
| **Architecture** | `cosmicpython` (free online) |
| **Git-based** | `mkdocs`, `aidlc-rules` |

> **Add your own**: Edit `deployment.json` to add any documentation source - websites, git repos, or local markdown files.

---

## Documentation

📚 **[Full Documentation](https://pankaj28843.github.io/docs-mcp-server/)**

- **Tutorials**: [Getting Started](https://pankaj28843.github.io/docs-mcp-server/tutorials/getting-started/), Adding Tenants
- **How-To Guides**: Git Tenants, Debugging, Docker Deployment
- **Reference**: deployment.json Schema, CLI Commands, MCP Tools
- **Explanations**: Architecture, BM25 Ranking, Sync Strategies

To build documentation locally:
```bash
uv sync --extra dev
uv run mkdocs serve
```

---

## License

MIT License - See [LICENSE](LICENSE)
