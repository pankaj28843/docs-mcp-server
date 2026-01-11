# Product Overview - docs-mcp-server

## Purpose
Multi-tenant Model Context Protocol (MCP) server that provides AI assistants with unified access to documentation sources. Eliminates AI hallucinations by grounding responses in real documentation from Django, FastAPI, Python, pytest, and other technical sources.

## Target Users
- **Developers** using AI assistants (VS Code Copilot, Claude Desktop) who need accurate, cited documentation
- **Teams** wanting to serve internal documentation alongside public sources
- **Organizations** requiring offline-ready documentation search with BM25 ranking

## Key Features
- **Multi-Tenant Architecture**: Serve unlimited doc sources from one container
- **Smart Search**: BM25 with IDF floor - works for 7 docs or 2500 docs
- **Auto-Sync**: Scheduled crawlers for websites, git syncs for repos
- **MCP Native**: Standard tools (search, fetch, browse) for AI assistants
- **Offline-Ready**: Filesystem tenants for local markdown

## Business Objectives
- **Stop AI hallucinations** by providing real documentation citations
- **Reduce context switching** between AI chat and documentation sites
- **Enable offline development** with cached documentation
- **Scale documentation access** across teams and projects

## Success Metrics
- Search accuracy and relevance scores
- Documentation freshness (sync success rates)
- AI assistant integration adoption
- Query response times under 100ms
- Zero-downtime deployments

## Technical Constraints
- Python 3.10+ required
- Docker for deployment workflows
- BM25 search algorithm (no vector embeddings)
- FastMCP protocol compliance
- Ripgrep for text search performance
