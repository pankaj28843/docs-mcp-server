---
mode: 'agent'
description: 'Create a PRP plan for docs-mcp-server without code changes until approved'
tools: ['read', 'search', 'web', 'mcp_techdocs/*']
---

# Product Requirement Prompt (PRP) Planning

Create or update a PRP plan aligned with `.github/instructions/PRP-README.md`. **No code edits, migrations, config changes, or tests** until stakeholders approve.

## Context Gathering

Before drafting, gather facts using these sources:

**Project files**:
- `deployment.json` — tenant configurations
- `src/docs_mcp_server/tenant.py` — DDD aggregate pattern
- `src/docs_mcp_server/app.py` — ASGI entry, tenant routing
- `.github/copilot-instructions.md` — prime directives

**TechDocs research** (use `#techdocs`):
- `cosmicpython` — Repository, Unit of Work, DDD patterns
- `fastmcp` / `mcp` — MCP tool schemas, context
- `pytest` — fixture patterns, test organization

Run `list_tenants` first, then `describe_tenant` for optimal query patterns.

## Non-Negotiable: “Do next steps” contract must be included in every plan
Every plan you create/update **MUST** contain a section titled:

- `## Plan Operator Contract (“Do next steps”)`

That section must explicitly encode the following behavior so the user never has to repeat it:

- When the user says **“Do next steps”** (or “yes do the next steps”), the agent must:
  1. Re-open and re-check the plan file first.
  2. Interpret “next” as the next **incomplete checkbox items** from the earliest incomplete phase in **Implementation Blueprint**.
  3. If uncertain, re-check **`## What else remains?`** and proceed from the topmost unfinished item.
  4. After each work chunk, update the plan (Status Snapshot + blockers + checklist + What else remains).
  5. If all plan items are complete: redeploy + full validation loop; record results.
  6. If plan items remain: implement what remains immediately; stop only when done or when a blocker is recorded.

Also require the plan to include:
- `## Status Snapshot (YYYY-MM-DD)` (newest first)
- `## Plan Watchers` (status cadence + blockers)
- `## What else remains?` (single source of truth list, kept in sync with checkboxes)

## Required Sections (in the plan output)
1. **Plan Operator Contract (“Do next steps”)** (required; see above)
2. **Status Snapshot (YYYY-MM-DD)** (required; newest first)
3. **Goal / Why / Success Metrics** (tie back to measurable outcomes)
4. **Current State** (existing modules, dependencies, outstanding gaps, references to specific files/lines)
5. **Implementation Blueprint** (phased work packages mapped to files + TechDocs evidence)
   - MUST be a checkbox-driven checklist so “next steps” is deterministic
6. **Context & Anti-Patterns** (cite Cosmic Python patterns, blocked approaches, known gotchas)
7. **Validation Loop** (commands per phase: `uv run ruff format .`, `uv run ruff check --fix .`, `timeout 60 uv run pytest -m unit --no-cov`, `uv run python debug_multi_tenant.py`)
8. **Open Questions & Risks** (blockers, missing context, required approvals)
9. **Plan Watchers** (status cadence, blockers, decision log if needed)
10. **What else remains?** (required; synced with Implementation Blueprint)

## Process
- Gather facts from repo files, `deployment.json`, and existing docs before drafting conclusions.
- Use TechDocs citations (URL + snippet) for every pattern, architecture, or tooling claim.
- Keep bullets crisp; prefer ASCII tables for evidence matrices or decision summaries.
- Ensure every Implementation Blueprint step is specific:
  - explicit files
  - explicit intent
  - validation commands
  - exit criteria (“done when…”)
- End with a readiness statement: **"Ready to implement"** or **"Need clarification on X"** (but do not block on minor ambiguities; prefer clearly labeled assumptions).

## Output
- Save/update the plan under: `.github/ai-agent-plans/{date}-{slug}-plan.md`.
- Final response must:
  - recap key updates,
  - link to the plan file,
  - list unresolved questions or approvals needed before coding,
  - and explicitly confirm the plan includes the **Plan Operator Contract**, **Status Snapshot**, and **What else remains?** sections.
