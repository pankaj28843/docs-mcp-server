---
name: coverageHandoff
description: Continue a multi-iteration coverage push, documenting MCP tooling and next steps.
argument-hint: planPath="tasks.md" target="src/docs_mcp_server/search/"
---

## TechDocs Research
Use `#techdocs` to ground testing patterns. Key tenants: `pytest`, `python`, `cosmicpython`. Follow **.github/instructions/techdocs.instructions.md** for the full workflow.

## Goals
- Resume a coverage push tracked in a shared markdown plan (argument `planPath`, default `tasks.md`).
- Ensure anyone can pick up where you leave off and steadily move toward >=80% coverage.

## Workflow
1. **Load and respect the plan**
   - Read the referenced plan file in full before acting.
   - Capture the latest iteration number, coverage snapshot, and in-flight checklist items.
   - Never author a new plan file unless the current plan explicitly orders you to do so.

2. **Honor the coverage workflow pattern**
   - Default loop: identify slice → code/tests → `timeout 60 uv run pytest -m unit --cov=src/docs_mcp_server --cov-report=term` → record deltas in the plan.
   - Anti-patterns to flag: skipping the timeout-wrapped coverage command, forgetting to update the plan, letting paths rot.

3. **Mandated TechDocs MCP sequence (no exceptions)**
   - Before touching repo files, run:
     1. `mcp_techdocs_list_tenants` to confirm available sources.
     2. `mcp_techdocs_describe_tenant` for the tenant or codename you will reference.
     3. `mcp_techdocs_root_search` scoped to that tenant.
     4. `mcp_techdocs_root_fetch` on at least one search result.
   - Capture the takeaways in your notes.

4. **Summarize current progress**
   - Report what was attempted, what passed/failed, and which checklist items moved.
   - Note blockers, flaky steps, or tooling gaps so the next engineer inherits full context.

5. **Plan the next iteration**
   - Point to the next unchecked plan items, justify why those targets advance coverage fastest, and include remaining commands.

## Output
- Updated status summary tied back to `planPath`.
- TechDocs-backed list of patterns/tools with usage guidance.
- Clarified patterns/anti-patterns and concrete next steps.
