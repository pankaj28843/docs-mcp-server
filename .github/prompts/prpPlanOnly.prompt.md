---
name: prpPlanOnly
description: Produce a Product Requirement Prompt (PRP) plan without touching code until explicitly approved.
argument-hint: brief="one-line objective" scope="files/domains in play"
---

## TechDocs Research
Use `#techdocs` to ground every assertion. Prioritize `cosmicpython` (DDD patterns), `fastmcp`/`mcp` (tool schemas), and `github-copilot` (prompt files). Run `list_tenants` to discover additional documentation sources. Reference **.github/instructions/techdocs.instructions.md** for detailed strategies.

## Mission
- Draft or update a PRP aligned with `.github/instructions/PRP-README.md`.
- Stay in planning mode: no code edits, migrations, config changes, or tests until stakeholders approve.
- Apply AI-DLC planning rules so each step is explicit before execution.

## Required Sections
1. **Goal / Why / Success Metrics** (tie back to measurable outcomes)
2. **Current State** (existing modules, dependencies, outstanding gaps, references to specific files/lines)
3. **Implementation Blueprint** (phased work packages mapped to files + TechDocs evidence)
4. **Context & Anti-Patterns** (cite Cosmic Python patterns, blocked approaches, known gotchas)
5. **Validation Loop** (commands per phase: `uv run ruff format .`, `uv run ruff check --fix .`, `timeout 60 uv run pytest -m unit --no-cov`, `uv run python debug_multi_tenant.py`)
6. **Open Questions & Risks** (blockers, missing context, required approvals)

## Process
- Gather facts from repo files, `deployment.json`, and existing docs before drafting conclusions.
- Use TechDocs citations (URL + snippet) for every pattern, architecture, or tooling claim.
- Keep bullets crisp; prefer ASCII tables for evidence matrices or decision summaries.
- End with a readiness statement ("Ready to implement", "Need clarification on X", etc.).

## Output
- Save/update the plan under `.github/ai-agent-plans/{date}-{slug}-plan.md`.
- Final response must recap key updates, link to the plan file, and list unresolved questions or approvals needed before coding.
