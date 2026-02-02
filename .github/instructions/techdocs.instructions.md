# TechDocs MCP Instructions

> **Summary**: TechDocs provides instant access to authoritative documentation sources—Django, DRF, FastAPI, Python, and more. Use it to ground decisions in official docs rather than guessing.

---

## Quick Reference

| Tool | When to Use | Example |
|------|-------------|---------|
| `list_tenants` | Discover available docs, confirm tenant exists | **Start every research session here** |
| `find_tenant` | Find tenants by topic (fuzzy search) | `find_tenant("django")` finds django, drf |
| `describe_tenant` | Get test_queries, source_type, url_prefixes | Before searching—reveals good query patterns |
| `root_search` | Find relevant pages by keyword/phrase | `query="select_related prefetch_related"` |
| `root_fetch` | Read full document content | After search returns a high-score result |

---

## Recommended Workflow

**Always follow this discovery pattern:**

```python
# 1. List available tenants (they change over time)
mcp_techdocs_list_tenants()

# 2. Describe the tenant to get query hints
mcp_techdocs_describe_tenant(codename="django")

# 3. Search using test_queries as inspiration
mcp_techdocs_root_search(tenant_codename="django", query="select_related prefetch_related")

# 4. Fetch the most relevant result
mcp_techdocs_root_fetch(tenant_codename="django", uri="https://docs.djangoproject.com/...")
```

**Why this order matters:**
- `list_tenants` reveals what's available—tenants are added frequently
- `describe_tenant` returns `test_queries` that show which terms work well
- Searching without describe_tenant often leads to poor results

---

## Core Tenants

### Python/FastMCP Stack
| Codename | Scope | Sample Queries |
|----------|-------|----------------|
| `fastapi` | FastAPI framework, async patterns, OpenAPI | `async endpoint`, `dependency injection`, `OpenAPI` |
| `fastmcp` | MCP server implementation, tools, prompts | `tool decorator`, `context`, `prompt files` |
| `mcp` | Model Context Protocol specification | `tool schema`, `resource`, `sampling` |
| `python` | Stdlib, async, typing, context managers | `async def`, `context manager`, `typing` |
| `pytest` | Fixtures, parametrize, mocking | `@pytest.fixture`, `parametrize`, `mock` |

### Django/DRF
| Codename | Scope | Sample Queries |
|----------|-------|----------------|
| `django` | Models, views, ORM, signals, settings | `select_related`, `prefetch_related`, `signals` |
| `drf` | Serializers, viewsets, permissions | `ModelSerializer`, `viewsets`, `permissions` |

### Architecture & Patterns
| Codename | Scope | Sample Queries |
|----------|-------|----------------|
| `cosmicpython` | DDD, Repository, Unit of Work patterns (free online) | `repository pattern`, `unit of work`, `aggregate` |

> **Note**: For clean code principles, design patterns, and architecture guidance, run `list_tenants` to discover available documentation sources. Users can add their own architecture-related tenants via filesystem or git sources.

### AI & Agents
| Codename | Scope | Sample Queries |
|----------|-------|----------------|
| `github-copilot` | Copilot customization, instructions, prompts | `custom instructions`, `prompt files`, `coding agent` |
| `strands-sdk` | Multi-agent systems, orchestration | `agent`, `orchestration`, `tools` |
| `aws-bedrock-agentcore` | AWS Bedrock agents | `agent`, `bedrock`, `API` |

---

## Git Tenants (Preferred for Sustainability)

**Prefer git tenants over online tenants** when the documentation is in a public repo:
- Git sync is lighter on resources than web crawling
- Updates are tracked via git, not re-crawled
- Works offline once synced

Example git tenants:
- `mkdocs` - MkDocs documentation from GitHub
- `aidlc-rules` - AWS AIDLC rules from GitHub

```python
# Search a git tenant
mcp_techdocs_root_search(tenant_codename="mkdocs", query="configuration")
```

---

## Search Strategy

### DO
- **Start with `list_tenants`** at session start—new docs appear regularly
- **Use `describe_tenant`** to discover optimal query patterns from `test_queries`
- **Try multiple query variations** if initial searches miss (3-5 attempts)
- **Fetch only high-score (>50) results** to avoid noise
- **Cite sources** in code comments when patterns come from docs

### DON'T
- Skip `describe_tenant`—the `test_queries` often have the exact term you need
- Assume you know what's available—tenants are added frequently
- Give up after one search—try alternate phrasings
- Fetch low-score results hoping for relevance

---

## Troubleshooting

| Issue | Action |
|-------|--------|
| No hits for a term | Run `describe_tenant` and search for related terms from `test_queries` |
| Need implementation examples | Fetch the doc and look for code blocks |
| Research feels stale | `list_tenants` to confirm tenant exists and check for updates |
| Unsure which tenant to use | Start with `list_tenants`, filter by topic area |
