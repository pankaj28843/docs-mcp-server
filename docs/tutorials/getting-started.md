# Tutorial: Getting Started with docs-mcp-server

**Time**: ~15 minutes  
**Prerequisites**: Python 3.10+, uv package manager installed  
**What You'll Learn**: Deploy your first documentation tenant and perform searches

---

## Step 1: Clone the Repository

```bash
git clone https://github.com/pankaj28843/docs-mcp-server.git
cd docs-mcp-server
```

**Expected output**:
```
Cloning into 'docs-mcp-server'...
remote: Enumerating objects: ...
```

---

## Step 2: Install Dependencies

```bash
uv sync
```

This installs all Python dependencies listed in `pyproject.toml`, including FastMCP, httpx, BeautifulSoup4, and search libraries.

**Expected output**:
```
Resolved 120+ packages in 2s
Installed 120+ packages in 5s
```

---

## Step 3: Start a Test Server

Use the debug script to start a temporary server with Django documentation:

```bash
uv run python debug_multi_tenant.py --tenant django --test search
```

**Expected output**:
```
✓ Health check passed
✓ Search returned 10 results for 'ModelForm validation'
   [1] Django ModelForm validation (score: 42.3)
   [2] Form and field validation (score: 38.1)
   ...
```

This script:
- Starts a local server on port 42043
- Performs a test search query
- Shuts down cleanly after tests

---

## Step 4: Search Documentation

With the server running (use `--keep-alive` flag), you can search via HTTP:

```bash
# In another terminal
curl "http://localhost:42043/django/search?query=forms+validation" | jq .
```

**Example response**:
```json
{
  "results": [
    {
      "title": "Form and field validation",
      "url": "https://docs.djangoproject.com/en/5.1/ref/forms/validation/",
      "score": 42.3,
      "snippet": "Form validation happens when the data is cleaned..."
    }
  ]
}
```

---

## Step 5: Deploy to Docker (Production)

For production deployment with all tenants:

```bash
uv run python deploy_multi_tenant.py --mode online
```

This builds a Docker container with your configured documentation tenants and starts it on port 42042.

> **Tip**: Edit `deployment.json` to add your own documentation sources before deploying.

**Verify deployment**:
```bash
curl http://localhost:42042/health
```

---

## Verification

You should now have:
- ✅ A working local environment with `uv sync`
- ✅ Successfully tested Django documentation search
- ✅ Docker container deployed (optional)

---

## Next Steps

- **How-To**: [Add Your First Tenant](../how-to/configure-online-tenant.md) - Configure a custom documentation source
- **Reference**: [CLI Commands](../reference/cli-commands.md) - All available scripts
- **Explanation**: [Architecture Overview](../explanations/architecture.md) - Understand the system design

---

## Troubleshooting

**Problem**: `uv: command not found`  
**Fix**: Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`

**Problem**: Port 42043 already in use  
**Fix**: Kill existing server: `pkill -f "python -m docs_mcp_server"` or use a different port

**Problem**: Test search returns 0 results  
**Fix**: Check if `mcp-data/django/` directory exists and contains `.md` files. If not, run: `uv run python trigger_all_syncs.py --tenants django --force`

---

**Tutorial Complete!** You've successfully deployed docs-mcp-server locally. Ready for [more advanced configuration](../tutorials/adding-first-tenant.md)?
