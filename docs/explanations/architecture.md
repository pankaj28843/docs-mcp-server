# Explanation: Architecture

**Audience**: Engineers integrating or extending docs-mcp-server.  
**Prerequisites**: Familiar with Python async, Docker, and MCP.  
**What you'll learn**: How tenants, sync, search, and MCP tools fit together; trade-offs and alternatives.

## The Problem
Teams juggle many documentation sources (web, git, local). AI assistants need one interface to search all of them with consistent ranking and fresh content.

## Our Approach
- **Multi-tenant FastMCP**: Each tenant exposes MCP tools (`root_search`, `root_fetch`, `root_browse`) behind one HTTP endpoint.
- **BM25 Search**: Documents are indexed with BM25 + IDF floor to keep scores positive across small/large corpora.
- **Sync Paths**: Online tenants use crawlers; git tenants use `GitRepoSyncer`; filesystem tenants read local markdown. All feed search segments.
- **Snippet + Fetch**: Search returns scored hits with snippets; `fetch` returns full content from cache.

## Data Flow
1. **Sync**: `trigger_all_syncs.py` crawls or git-pulls content into `mcp-data/<tenant>`.
2. **Index**: `trigger_all_indexing.py` builds BM25 segments under `__search_segments`.
3. **Serve**: FastMCP reads segments; MCP tools answer `search` and `fetch`.
4. **Clients**: VS Code/Claude call MCP endpoint at `http://127.0.0.1:42042/mcp`.

## Trade-offs
- **Single BM25 tuning**: One set of parameters for all tenants (no per-tenant tuning) keeps config simple; we rely on IDF floor and length norm for stability.
- **Crawl vs Git**: Git tenants are faster and deterministic; online tenants offer freshness but depend on robots/HTML stability.
- **No cache for search results**: Queries vary widely; caching is low-yield and can hide freshness issues.

## Alternatives Considered

| Approach | Pros | Cons | Why Not Chosen |
|----------|------|------|----------------|
| TF-IDF only | Simple, fast | Negative scores on small corpora, weaker relevance | BM25 with IDF floor performs better on docs |
| Per-tenant ranking params | Tunable per corpus | Complexity in config, harder ops | Prefer smart defaults and code-side fixes |
| Heavy vector search | Great semantic recall | Higher infra cost, slower cold starts | BM25 is sufficient for structured docs |

## Verification Hooks
- Capture command outputs during validation runs for deploy/sync/index/search.
- `uv run mkdocs build --strict` keeps navigation and links in sync with code.

## Related
- [Search Ranking (BM25)](search-ranking.md)
- [Sync Strategies](sync-strategies.md)
- Tests: see `tests/unit/test_bm25_engine.py` and `tests/unit/tools/test_cleanup_segments.py` for behavior-focused coverage.

