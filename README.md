# docs-mcp-server

An [MCP server](https://modelcontextprotocol.io/) that gives AI assistants access to your documentation through BM25-powered search. Aggregate docs from websites, git repos, and local files into a single searchable API.

**Who it's for**: Developers using AI assistants (VS Code Copilot, Claude Desktop) who want accurate, up-to-date answers from their actual documentation instead of stale training data.

**What it does**: Runs a multi-tenant server where each tenant is a documentation source (Django docs, your internal wiki, any markdown repo). AI assistants call MCP tools to search, fetch, and browse — getting real snippets and URLs instead of guessing.

[![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://pankaj28843.github.io/docs-mcp-server/)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Key Features

| Feature | Description |
|---------|-------------|
| 🎯 **Multi-Tenant** | One container serves unlimited documentation sources |
| 🔍 **BM25 Search** | SQLite-backed search with positive scores across 7–2500+ docs per tenant |
| 🔄 **Auto-Sync** | Scheduled crawlers (websites), git pulls (repos), or direct filesystem reads |
| 🚀 **MCP Native** | Standard tools (`list_tenants`, `find_tenant`, `describe_tenant`, `root_search`, `root_fetch`) |
| 📚 **Three Source Types** | Online (sitemap/crawler), Git (sparse checkout), Filesystem (local markdown) |

---

## Prerequisites

- **Python 3.12+** — [Installation guide](https://docs.python.org/3/using/index.html)
- **uv** — [Installation guide](https://docs.astral.sh/uv/getting-started/installation/)
- **Docker** — [Installation guide](https://docs.docker.com/get-docker/)

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
| `aws-bedrock-agentcore` | AWS Bedrock AgentCore | Online (crawler) |
| `strands-sdk` | Strands Agents SDK | Online (crawler) |
| `cosmicpython` | Architecture patterns | Online (crawler) |
| `mkdocs` | MkDocs docs | Git (GitHub) |
| `aidlc-rules` | AIDLC workflow rules | Git (GitHub) |

Configure additional sources by editing `deployment.json`. See [deployment.json Schema](https://pankaj28843.github.io/docs-mcp-server/reference/deployment-json-schema/).

---

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
