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
- Optional for docs: `uv sync --extra dev` to install `mkdocs` and `mkdocs-material` (see Reality Log).

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

## Quick Start (Fresh Clone)

Follow these steps in order (outputs below are from the latest run).

### Step 1: Clone and Install

```bash
git clone https://github.com/pankaj28843/docs-mcp-server.git
cd docs-mcp-server
uv sync
```

### Step 2: Create Your Configuration

```bash
cp deployment.example.json deployment.json
```

### Step 3: Deploy to Docker (online mode)

```bash
uv run python deploy_multi_tenant.py --mode online
```

Actual output (2025-12-31):
```
#17 naming to docker.io/pankaj28843/docs-mcp-server:multi-tenant done
🛑 Stopping existing container...
🚀 Starting container on port 42042 in online mode...
✅ Deployment complete!
Server URL │ http://127.0.0.1:42042
```

Container check:
```
docker ps | grep docs-mcp
... docs-mcp-server-multi ... Up (healthy) ... 0.0.0.0:42042->42042/tcp
```

### Step 4: Trigger Initial Sync (online + git tenants)

```bash
uv run python trigger_all_syncs.py --tenants drf --force
uv run python trigger_all_syncs.py --tenants aidlc-rules --force
```

Outputs:
```
uv sync --extra dev
aidlc-rules                    ✅ Git sync completed: 25 files, commit 5119d001
```

### Step 5: Rebuild Indexes

```bash
uv run python trigger_all_indexing.py --tenants drf django mkdocs aidlc-rules
```

Outputs:
```
drf indexed 44 docs
django indexed 271 docs
mkdocs indexed 19 docs
aidlc-rules indexed 25 docs
```

### Step 6: Test Search

```bash
uv run python debug_multi_tenant.py --tenant drf --test search
```

Output excerpt:
```
✅ Search successful, returned 5 results
"Renderers" ...
```

### Step 7: Connect VS Code
uv run mkdocs serve
```

---

## License

MIT License - See [LICENSE](LICENSE)
