# docs-mcp-server

Multi-tenant [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for documentation search and retrieval.

Use one server to index docs from websites, git repositories, and local markdown folders, then expose them to AI clients through a clean MCP toolset.

[![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://pankaj28843.github.io/docs-mcp-server/)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Why this project exists

LLM answers are only as good as their context. `docs-mcp-server` makes your assistant query your real docs instead of relying on stale model memory.

- Run a single MCP endpoint for many documentation tenants.
- Keep sources fresh with scheduler-driven sync.
- Return ranked snippets and full documents with source URLs.

## Who this is for

- Teams using MCP-compatible clients (Copilot, Claude, custom tools).
- Platform/dev experience teams curating internal + external docs.
- Engineers who want deterministic, inspectable doc retrieval.

## Quick start (10–15 minutes)

```bash
git clone https://github.com/pankaj28843/docs-mcp-server.git
cd docs-mcp-server
uv sync
cp deployment.example.json deployment.json
uv run python deploy_multi_tenant.py --mode online
uv run python trigger_all_syncs.py --tenants drf --force
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

If search returns ranked results with URLs/snippets, your tenant is live.

Add to `~/.config/Code/User/mcp.json`:

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

## Documentation map

- Start here: `docs/index.md`
- First-time walkthrough: `docs/tutorials/getting-started.md`
- Operational recipes: `docs/how-to/`
- API and config lookup: `docs/reference/`
- Architecture and trade-offs: `docs/explanations/`

## Core tools exposed via MCP

- `list_tenants`
- `find_tenant`
- `describe_tenant`
- `root_search`
- `root_fetch`

See full contracts in `docs/reference/mcp-tools.md`.

## Contributing and quality gates

Development + CI validation loop:

```bash
uv run ruff format . && uv run ruff check --fix .
timeout 120 uv run pytest -m unit --cov=src/docs_mcp_server --cov-fail-under=95
timeout 120 uv run python integration_tests/ci_mcp_test.py
uv run mkdocs build --strict
```

More in `docs/contributing.md`.

## License

MIT — see `LICENSE`.
