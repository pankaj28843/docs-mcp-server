---
name: deadCodeAudit
description: Systematically identify dead/unused code with evidence-based prioritized removal candidates
argument-hint: Optional focus area (e.g., "src/", "services/", specific module)
---

You are a deep-code-audit agent working under feature-freeze constraints. Analyze, document, and then remove dead or no-longer-relevant code with full validation coverage.

## Goal

Identify, document, and eliminate dead code in the target area with evidence that the change is safe. 

**"Relevant" still means:** reachable from production behavior (entrypoints, schedulers, deployment scripts, MCP routes). Test-only references or dev scripts do **not** keep code alive.

## Critical Operations Scripts (NEVER BREAK)

These scripts are essential for daily operations. **Every dead code removal MUST verify they still work:**

| Script | Purpose | Validation Command |
|--------|---------|-------------------|
| `debug_multi_tenant.py` | Local + remote testing, MCP tool validation | `uv run python debug_multi_tenant.py --tenant drf --test search` |
| `deploy_multi_tenant.py` | Docker deployment (ALWAYS online mode) | `uv run python deploy_multi_tenant.py --mode online` |
| `trigger_all_syncs.py` | Crawler/sync jobs for online tenants | `uv run python trigger_all_syncs.py --tenants drf --force` |
| `trigger_all_indexing.py` | Rebuild BM25 search indexes | `uv run python trigger_all_indexing.py --tenants drf django` |
| `sync_tenant_data.py` | Export/import tenant data across machines | `uv run python sync_tenant_data.py export --tenants drf --dry-run` |

**Script Dependency Rules:**
- `deploy_multi_tenant.py`: Always use `--mode online` for production parity
- `trigger_all_syncs.py`: Use `--force` for small tenants (e.g., drf) to test full crawl path
- `trigger_all_indexing.py`: Run for ALL tenant types (filesystem, online, git) to verify index building
- `debug_multi_tenant.py`: Test both local (`--tenant drf`) and remote (`--host localhost --port 42042 --tenant drf`)

## Workflow (Follow In Order)

### 0. Pinned Directives
- Follow `.github/copilot-instructions.md` for Core Philosophy (NO BACKWARD COMPATIBILITY, LESS CODE) and Prime Directives (uv run, green-before-done)
- See `.github/instructions/validation.instructions.md` for validation loop requirements
- Never manage servers manually; always use `debug_multi_tenant.py`/`deploy_multi_tenant.py` for lifecycle checks.

### 1. Evidence Pass
1. Capture current repo state (`git status -sb`).
2. Run `uv run vulture src/ --min-confidence 60` and note flagged symbols.
3. Run `uv run ruff check --select F401,F841 src/docs_mcp_server` for unused imports/vars.
4. Use `rg -n "SYMBOL"` to confirm reachability; collect excerpts you will reference later.

### 2. Living PRP Plan
- Immediately create/update `.github/ai-agent-plans/{date}-dead-code-plan.md` using the PRP structure in `.github/instructions/PRP-README.md`.
- Log discoveries, decisions, and scope adjustments as you go. No retroactive fill-ins.

### 3. Map Entrypoints & Dependencies
- List production entrypoints (app.py, tenant.py, debug/deploy scripts, CLI tools).
- Trace import chains to ensure flagged code is not indirectly registered.

### 4. Candidate Confirmation
- For every candidate capture: exact path::symbol, tool evidence, `rg` output, and why it is safe to delete.
- Prefer small, high-confidence batches. If uncertainty remains, park it in "Open Questions".

### 5. Execute Deletions
- Remove code rather than stub/`pass`. Delete unused tests alongside code.
- Clean up imports, type hints, and configuration that referenced the removed symbols.
- Update docs only if behavior visible to users changed—never add summary docs.

### 6. Validation Loop (Run After Each Batch)

**Phase 1: Code Quality**
1. `uv run ruff format .`
2. `uv run ruff check --fix .`
3. `get_errors` on every touched Python file; resolve all diagnostics.
4. `timeout 120 uv run pytest -m unit --no-cov`

**Phase 2: Local Testing**
5. `uv run python debug_multi_tenant.py --tenant drf --test search` (small online tenant)
6. `uv run python debug_multi_tenant.py --tenant django --test search` (large online tenant)
7. `uv run python debug_multi_tenant.py --tenant mkdocs --test search` (git tenant)

**Phase 3: Deploy & Remote Testing**
8. `uv run python deploy_multi_tenant.py --mode online` (MANDATORY: always online mode)
9. `uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search`
10. `mcp_techdocs_describe_tenant(codename="drf")` (prove MCP reachability)

**Phase 4: Sync & Index Validation (Critical for crawler/storage changes)**
11. `uv run python trigger_all_syncs.py --tenants drf --force` (force crawl small online tenant)
12. `uv run python trigger_all_syncs.py --tenants aidlc-rules --force` (force sync git tenant)
13. `uv run python trigger_all_indexing.py --tenants drf django mkdocs aidlc-rules` (all tenant types: online, git)
14. Verify sync via: `curl http://localhost:42042/drf/sync/status | jq .`
15. Verify git sync: `curl http://localhost:42042/aidlc-rules/sync/status | jq .`

**Phase 5: Data Export Validation (if touching storage paths)**
16. `uv run python sync_tenant_data.py export --tenants drf --dry-run` (verify export still works)

Re-run loop from the top after fixes until every command is green.

### Tenant Coverage Requirements
- Always exercise a representative spread of tenants: pick 3-4 filesystem, 3-4 online, and **ALL git tenants** per validation round so regressions surface quickly without brute-forcing all tenants.
- **Git tenants are critical:** Unlike online/filesystem tenants, git tenants use `GitRepoSyncer` and `GitSyncSchedulerService` which have their own sync path. Always test at least one git tenant.
- Use `debug_multi_tenant.py --tenant <codename> --test search|fetch|browse` for local runs and pair each local check with the remote variant (`--host localhost --port 42042`).
- Rotate the sample set between rounds; prefer smaller tenants for speedy crawler/sync trials while still covering large/critical tenants over time.

### Git Tenant Validation (MANDATORY)
Git tenants (`source_type: "git"`) use a completely separate sync path from online tenants:
- `GitRepoSyncer` (in `utils/git_sync.py`) handles sparse checkout + export
- `GitSyncSchedulerService` (in `services/git_sync_scheduler_service.py`) manages scheduled syncs
- These are instantiated in `tenant.py` for git tenants only

**Always run these checks before removing any code:**
1. `rg -n "GitRepoSyncer|GitSyncScheduler" src/` - Check for usage in tenant.py
2. `uv run python trigger_all_syncs.py --tenants aidlc-rules --force` - Force sync a git tenant
3. `curl http://localhost:42042/aidlc-rules/sync/status | jq .` - Verify sync completed
4. Check deployment.json for `source_type: "git"` tenants to ensure they're still supported

### Feature-Specific Debug Hooks

**Core request surface (list/describe/search/fetch/browse):**
- Run every MCP operation locally and remotely for each sampled tenant type
- Use `debug_multi_tenant.py --tenant <codename> --test search|fetch|browse`

**Crawler/sync logic:**
- Trigger sync for small online tenant: `uv run python trigger_all_syncs.py --tenants drf --force`
- Trigger sync for git tenant: `uv run python trigger_all_syncs.py --tenants aidlc-rules --force`
- Check sync status: `curl http://localhost:42042/drf/sync/status | jq .`
- Check git sync status: `curl http://localhost:42042/aidlc-rules/sync/status | jq .`
- Inspect logs: `docker logs docs-mcp-server-multi 2>&1 | rg -n "ERROR|WARN|crawl|git"`
- Manual sync trigger: `curl -X POST http://localhost:42042/drf/sync/trigger`

**Search/index updates:**
- Rebuild indexes: `uv run python trigger_all_indexing.py --tenants drf django mkdocs`
- Test search: `uv run python debug_multi_tenant.py --tenant drf --test search --word-match`
- Verify via MCP: `mcp_techdocs_root_search(tenant_codename="drf", query="serializer")`

**Storage/filesystem paths:**
- Test git tenants: `uv run python debug_multi_tenant.py --tenant mkdocs --test fetch`
- Verify export: `uv run python sync_tenant_data.py export --tenants drf --dry-run`
- Test both fetch modes: `root_fetch` with `context="surrounding"` and `context="full"`

**Deployment changes:**
- Always redeploy: `uv run python deploy_multi_tenant.py --mode online`
- Verify health: `curl http://localhost:42042/health | jq '.status'`
- Check container: `docker logs docs-mcp-server-multi 2>&1 | tail -50`

Document any feature-specific debug commands you run inside the PRP validation log so future passes know exactly what ensured safety.

### 7. Reporting & Plan Output
- Keep the PRP plan updated with:
	- **Executive Summary** (candidate count, LOC saved, affected subsystems)
	- **Prioritized Candidate Table** with evidence + verification commands
	- **LOC Estimates by Category**
	- **Removal Priority Tiers** (Tier 1 delete now → Tier 4 needs confirmation)
	- **Validation Log** (record actual command outputs/status)
	- **Open Questions** requiring stakeholder input
- Reference specific files using repository-relative paths.

## Important Rules
1. Do not skip plan updates or evidence capture.
2. No manual git resets; never revert user changes.
3. Batch diffs narrowly—prefer many small deletions over one giant sweep.
4. Treat runtime decorators, plugin registries, and MCP tool wiring as potentially dynamic; confirm before deleting.
5. Remove associated tests/fixtures rather than leaving orphans.
6. If a candidate looks dynamic/reflective, add it to "Open Questions" instead of deleting.

## Anti-Patterns to Avoid
- Flagging symbols used via decorators, registry lookups, or tenant wiring without checking `tenant.py` and deployment configs.
- Forgetting to re-run full validation (lint → pytest → debug → deploy → MCP).
- Leaving "temporary" stubs, TODOs, or commented-out code.
- Collapsing plan + execution into a single step; the PRP plan must exist before deletions begin.
- **Breaking critical scripts:** Never delete code that `trigger_all_syncs.py`, `trigger_all_indexing.py`, `sync_tenant_data.py`, `deploy_multi_tenant.py`, or `debug_multi_tenant.py` depend on without verifying they still work.
- **Skipping online mode deployment:** Always use `--mode online` with `deploy_multi_tenant.py` to ensure sync/crawler paths are exercised.
- **Not testing small tenant sync:** Always run `trigger_all_syncs.py --tenants drf --force` to verify crawler still works.
- **Not testing git tenant sync:** Always run `trigger_all_syncs.py --tenants aidlc-workflows --force` to verify git sync still works. Git tenants use `GitRepoSyncer` and `GitSyncSchedulerService` which are separate from online crawler code.
- **Not testing all tenant types:** Always run `trigger_all_indexing.py` for filesystem, online, AND git tenants.
- **Deleting git sync code without checking tenant.py:** The `GitRepoSyncer` and `GitSyncSchedulerService` may appear "dead" via vulture but are instantiated conditionally in `tenant.py` for `source_type: "git"` tenants. Always `rg -n "GitRepoSyncer|GitSyncScheduler" src/` before deleting.
