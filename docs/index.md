# docs-mcp-server documentation

Welcome. This documentation is organized for newcomers first, then operators, then contributors.

If this is your first time here, start with the tutorial and do not skip verification steps.

## Start here

- New to the project: [Tutorial: Get running in 15 minutes](tutorials/getting-started.md)
- Adding or editing tenants: [How-to guides](how-to/configure-online-tenant.md)
- Looking up schemas and commands: [Reference](reference/deployment-json-schema.md)
- Understanding architecture choices: [Explanations](explanations/architecture.md)

## What this server does

`docs-mcp-server` is a multi-tenant MCP server that:

- indexes documentation sources,
- ranks search results with BM25,
- serves tool responses over MCP,
- and keeps tenants fresh with schedulers.

## Why this structure

This project follows a Divio-style documentation model (tutorials, how-to, reference, explanations), similar to popular open-source documentation systems.

You should be able to answer four different questions quickly:

1. **How do I get started?** → Tutorials
2. **How do I solve task X?** → How-to guides
3. **What are the exact options/contracts?** → Reference
4. **Why is it designed this way?** → Explanations

## Documentation map

### Tutorials (learning)

- [Getting started](tutorials/getting-started.md)
- [Lightning talk walkthrough](tutorials/lightning-talk-walkthrough.md)
- [Adding your first tenant](tutorials/adding-first-tenant.md)
- [Custom search configuration](tutorials/custom-search.md)

### How-to guides (task-focused)

- [Configure online tenant](how-to/configure-online-tenant.md)
- [Configure git tenant](how-to/configure-git-tenant.md)
- [Deploy with Docker](how-to/deploy-docker.md)
- [Evaluate runtime modes](how-to/evaluate-runtime-modes.md)
- [Trigger syncs](how-to/trigger-syncs.md)
- [Tune search ranking](how-to/tune-search.md)
- [Debug crawlers](how-to/debug-crawlers.md)
- [Preview docs locally](how-to/preview-docs-locally.md)

### Reference (lookup)

- [deployment.json schema](reference/deployment-json-schema.md)
- [CLI commands](reference/cli-commands.md)
- [MCP tools API](reference/mcp-tools.md)
- [Entrypoint walkthrough](reference/entrypoint-walkthrough.md)
- [Core library map](reference/core-library-map.md)
- [Environment variables](reference/environment-variables.md)
- [Python API](reference/python-api.md)

### Explanations (why)

- [Architecture](explanations/architecture.md)
- [Runtime modes and Starlette integration](explanations/runtime-modes-and-starlette.md)
- [Search ranking (BM25)](explanations/search-ranking.md)
- [Sync strategies](explanations/sync-strategies.md)
- [Cosmic Python patterns](explanations/cosmic-python.md)
- [Observability](explanations/observability.md)

## Quick verification checklist

After setup, verify the core path end-to-end:

```bash
uv run python deploy_multi_tenant.py --mode online
uv run python trigger_all_syncs.py --tenants drf --force
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

Success means your search returns ranked results with URLs and snippets.

## Need to contribute?

See [Contributing](contributing.md) for development workflow, validation gates, and documentation standards.
