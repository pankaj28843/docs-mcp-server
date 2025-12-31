---
applyTo: "**/*.py,**/*.json,*.py,*.json,deployment.json,pyproject.toml"
---

# Mandatory Validation Rules

These validation steps MUST run after ANY code change (addition, edit, or deletion) in this repository.

## When to Run

- **After every code change** (add, edit, delete)
- **On demand** when explicitly requested
- **Before marking any task complete**

## Critical Operations Scripts

These scripts are essential for daily operations. **Every change MUST verify they still work:**

| Script | Purpose | Validation Command |
|--------|---------|-------------------|
| `debug_multi_tenant.py` | Local + remote testing, MCP tool validation | `uv run python debug_multi_tenant.py --tenant drf --test search` |
| `deploy_multi_tenant.py` | Docker deployment (ALWAYS online mode) | `uv run python deploy_multi_tenant.py --mode online` |
| `trigger_all_syncs.py` | Crawler/sync jobs for online tenants | `uv run python trigger_all_syncs.py --tenants drf --force` |
| `trigger_all_indexing.py` | Rebuild BM25 search indexes | `uv run python trigger_all_indexing.py --tenants drf django` |
| `sync_tenant_data.py` | Export/import tenant data across machines | `uv run python sync_tenant_data.py export --tenants drf --dry-run` |

## Validation Loop (MANDATORY)

### Phase 0: Documentation Toolchain Setup (run BEFORE docs/ or README changes)

```bash
uv sync --extra dev
uv run mkdocs --version
uv run mkdocs build --strict  # baseline check; fix warnings before editing docs
```

Run these in order after EVERY code change:

### Phase 1: Code Quality

```bash
# 1. Format and lint
uv run ruff format .
uv run ruff check --fix .

# 2. Check for type errors (use get_errors tool on changed files)
# Fix ALL errors before proceeding

# 3. Run unit tests
timeout 60 uv run pytest -m unit --no-cov
```

### Phase 1.5: Documentation Quality

**If you modified any files in `docs/` or created/updated documentation:**

```bash
# 1. Validate documentation build
uv run mkdocs build --strict

# 2. Preview documentation locally (optional but recommended)
uv run mkdocs serve  # Visit http://localhost:8000

# 3. Verify changes
# - All internal links work (caught by --strict)
# - New pages added to mkdocs.yml nav: section
# - Code examples are runnable and output correct
# - Divio quadrant is correct (Tutorial/How-To/Reference/Explanation)
# - Active voice, second person ("You run..." not "The user runs...")
# - Command outputs are real (run commands, paste actual output)
```

### Command Output Verification

When documenting commands:
1. Execute the command in your current environment.
2. Copy-paste the actual output into docs.
3. Never invent "Expected output:" blocks—use real terminal output.

This is an internal verification process; do not add verification comments to published docs.

**Common mkdocs build --strict errors:**

| Error | Cause | Fix |
|-------|-------|-----|
| `WARNING - Doc file 'X.md' is not in the nav` | File exists but not in mkdocs.yml | Add to `nav:` section in mkdocs.yml |
| `WARNING - A relative path to 'X.md' is included in nav but not found` | File in nav but doesn't exist | Create the file or remove from nav |
| `WARNING - Documentation file 'X.md' contains a link to 'Y.md' which is not found` | Broken internal link | Fix link path or create target file |

**See `.github/instructions/docs.instructions.md` for full documentation standards.**

### Phase 2: Local Testing

```bash
# 4. Test small online tenant
uv run python debug_multi_tenant.py --tenant drf --test search

# 5. Test large online tenant (optional but recommended)
uv run python debug_multi_tenant.py --tenant django --test search

# 6. Test git tenant
uv run python debug_multi_tenant.py --tenant mkdocs --test search

# 7. Test git tenant (alternate)
uv run python debug_multi_tenant.py --tenant aidlc-rules --test search
```

### Phase 3: Deploy & Remote Testing

```bash
# 7. Deploy to Docker (ALWAYS use --mode online)
uv run python deploy_multi_tenant.py --mode online

# 8. Test deployed container
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search

# 9. Verify MCP reachability
mcp_techdocs_describe_tenant(codename="drf")
```

### Phase 4: Sync & Index Validation (for crawler/storage changes)

```bash
# 11. Force crawl small online tenant
uv run python trigger_all_syncs.py --tenants drf --force

# 12. Force sync git tenant (CRITICAL: tests GitRepoSyncer path)
uv run python trigger_all_syncs.py --tenants aidlc-rules --force

# 13. Rebuild indexes for ALL tenant types (online, git)
uv run python trigger_all_indexing.py --tenants drf django mkdocs aidlc-rules

# 14. Verify online sync status
curl http://localhost:42042/drf/sync/status | jq .

# 15. Verify git sync status
curl http://localhost:42042/aidlc-rules/sync/status | jq .
```

### Phase 5: Data Export Validation (if touching storage paths)

```bash
# 13. Verify export still works
uv run python sync_tenant_data.py export --tenants drf --dry-run
```

## Quick Validation (Minimum Required)

For small changes, at minimum run:

```bash
uv run ruff format . && uv run ruff check --fix .
timeout 60 uv run pytest -m unit --no-cov
uv run python debug_multi_tenant.py --tenant drf --test search
```

## Script Dependency Rules

- `deploy_multi_tenant.py`: **Always use `--mode online`** for production parity
- `trigger_all_syncs.py`: Use `--force` for small tenants to test full crawl path
- `trigger_all_indexing.py`: Run for ALL tenant types (filesystem, online, git)
- `debug_multi_tenant.py`: Test both local and remote (`--host localhost --port 42042`)

## Tenant Coverage Requirements

Always test a representative spread:
- 1+ online tenant (e.g., `drf`, `django`)
- **ALL git tenants** (e.g., `mkdocs`, `aidlc-rules` - git sync uses separate `GitRepoSyncer` + `GitSyncSchedulerService` code path)

### Git Tenant Sync (CRITICAL)

Git tenants (`source_type: "git"`) use a completely different sync mechanism:
- `GitRepoSyncer` in `utils/git_sync.py` - sparse checkout + export
- `GitSyncSchedulerService` in `services/git_sync_scheduler_service.py` - scheduled syncs
- Instantiated conditionally in `tenant.py` for git tenants only

**Always verify git sync works after ANY code changes:**
```bash
# Check git tenants exist
rg '"source_type": "git"' deployment.json

# Force sync a git tenant
uv run python trigger_all_syncs.py --tenants aidlc-rules --force

# Verify sync completed
curl http://localhost:42042/aidlc-rules/sync/status | jq .
```

## Anti-Patterns to Avoid

- ❌ Skipping validation after "small" changes
- ❌ Using `--mode offline` with `deploy_multi_tenant.py`
- ❌ Not testing with `debug_multi_tenant.py` after changes
- ❌ Leaving failing tests
- ❌ Proceeding with type errors
- ❌ **Not testing git tenant sync** - git tenants use separate `GitRepoSyncer` code path
- ❌ **Deleting git sync code without checking tenant.py** - `GitRepoSyncer` and `GitSyncSchedulerService` are used by git tenants

## Definition of Done

A change is NOT complete until:

1. ✅ `uv run ruff format . && uv run ruff check --fix .` passes
2. ✅ No type errors in changed files
3. ✅ `timeout 60 uv run pytest -m unit --no-cov` passes
4. ✅ `mkdocs build --strict` passes (if docs/ changed)
5. ✅ `uv run python debug_multi_tenant.py --tenant drf --test search` passes (online tenant)
6. ✅ `uv run python debug_multi_tenant.py --tenant aidlc-rules --test search` passes (git tenant)
7. ✅ `uv run python trigger_all_syncs.py --tenants aidlc-rules --force` passes (git sync)
8. ✅ All critical scripts verified working
