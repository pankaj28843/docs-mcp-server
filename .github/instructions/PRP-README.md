## What is PRP?

**Product Requirement Prompt (PRP)**

### In short

A PRP is **PRD + curated codebase intelligence + agent/runbook** — the minimum viable packet an AI needs to plausibly ship production-ready code on the first pass.

Product Requirement Prompt (PRP) is a structured prompt methodology first established in summer 2024 with context engineering at heart. A PRP supplies an AI coding agent with everything it needs to deliver a vertical slice of working software — no more, no less.

### How PRP differs from a traditional PRD

A traditional PRD clarifies what the product must do and why customers need it, but deliberately avoids how it will be built.

A PRP keeps the goal and justification sections of a PRD yet adds three AI-critical layers:

- **Context**: precise file paths and content, library versions and library context, code snippets examples. LLMs generate higher-quality code when given direct, in-prompt references instead of broad descriptions.
- **Codebase intelligence**: project-specific patterns, gotchas, and anti-patterns (e.g., DDD aggregate conventions).
- **Agent/runbook**: phased implementation steps + validation commands and stop/go gates.

---

## Mandatory operating contract for every PRP plan

Every PRP plan **MUST** include an explicit operating contract so that when a user says **“Do next steps”** the agent knows exactly what “next” means without additional prompting.

### “Do next steps” protocol (required)

In any ongoing chat where the plan is selected/active:

1. **Always re-check the plan file first**  
   If there is *any* uncertainty about what “next” means, re-open the plan and consult:
   - the **Implementation Blueprint** checklists
   - the **What else remains?** section (required — see below)

2. **Interpret “next steps” deterministically**
   - “Next steps” = the **earliest/nearest incomplete checklist items** in the current phase.
   - Do **not** skip phases unless the plan explicitly allows parallelism.
   - If blocked, stop and **record the blocker in the plan** (see “Plan watchers” below), then proceed with the next unblocked item if one exists.

3. **After finishing work, update plan watchers**
   - Update the **Status Snapshot** (timestamped).
   - Update the checklist progress.
   - Update **What else remains?** so it remains the single source of truth.

4. **If everything is implemented**
   - **Redeploy** and run the **full validation loop** (end-to-end), not just unit tests.
   - Then write a final Status Snapshot that includes the redeploy + full validation evidence.

5. **If not everything is implemented**
   - Focus immediately on implementing what remains.
   - Stop when all plan items are done, or you hit a new blocker and have recorded it.

### Plan watchers requirement (required)

Each plan must include a status section designed for “plan watchers” (people skimming progress):

- A **Status Snapshot (YYYY-MM-DD)** block near the top (newest first)
- A **Blockers / Risks** area that stays current
- A **Status cadence** rule (when the agent must post/update snapshots)
- A **What else remains?** section that is kept current

> If the plan is never used, it still must contain this contract so the *first use* is unambiguous.

---

## Creating effective PRP plans

### When to create a PRP plan

Create a detailed PRP plan for **non-trivial** tasks that require:
- Multiple actions across several files or modules
- Complex logic that needs careful analysis before implementation
- Refactoring that impacts existing functionality
- Integration between multiple systems or services
- Testing strategy that spans multiple layers (unit, integration, e2e)

Skip PRP planning for trivial tasks like:
- Single file edits or bug fixes
- Adding simple fields to models
- Basic configuration changes
- Straightforward documentation updates

---

## Required PRP plan sections

A comprehensive PRP plan should include:

1. **Goal / Why / Success Metrics**
   - What: clear, specific description of what needs to be built/changed
   - Why: business justification and value proposition
   - Success criteria: measurable outcomes / acceptance criteria

2. **Current state**
   - Existing code review: what exists today + where
   - Dependencies: what modules/services are involved
   - Constraints: technical limits or requirements
   - Risks: what could go wrong and mitigation strategies
   - References to specific files/lines (preferred)

3. **Implementation blueprint**
   - Phased approach: sequential phases (with optional explicit parallelism)
   - File-by-file changes: specific files and what changes
   - Data structures: models, schema, migrations if needed
   - API changes: endpoints + contracts
   - Testing strategy: what to test and where
   - **Checklist format required**: each step must be a checkbox so “next” is computable.

4. **Context & anti-patterns**
   - Known project gotchas and patterns to follow/avoid
   - Code quality standards and tooling requirements
   - Integration points with existing systems
   - docs-mcp-server patterns: Cosmic Python, FastMCP, and BM25 conventions

5. **Validation loop**
   - Level 1: syntax/imports
   - Level 2: unit tests
   - Level 3: integration tests
   - Level 4: docker deploy + end-to-end validation

6. **Open questions & risks**
   - Blockers, missing context, required approvals
   - “If X happens, do Y” mitigations

7. **Plan watchers**
   - Status snapshot(s)
   - Blockers / risks
   - Status cadence
   - **What else remains?** (single source of truth for next steps)

---

## Anti-patterns in PRP planning

Avoid these planning mistakes:

### Over-planning trivial tasks
- Don’t create 50-line PRPs for single-method changes
- Skip formal planning for obvious implementations
- Use judgment — if it’s a 5-minute fix, just do it

### Under-analyzing complex changes
- Don’t start coding complex refactors without understanding current state
- Always analyze existing patterns before introducing new ones
- Map out dependencies and integration points first

### Generic implementation blueprints
- Avoid vague steps like “update the models” or “add tests”
- Include specific file paths, method names, and code patterns
- Reference existing code examples and conventions

### Missing anti-pattern analysis
- Always include project-specific patterns to follow/avoid
- Document quality standards and tooling requirements
- Include validation steps that catch common mistakes

### Inadequate context gathering
- Don’t assume — search existing codebase for similar patterns
- Include related code snippets and integration examples
- Document dependencies and potential side effects

---

## Example PRP plan quality markers

High-quality PRP plan indicators:
- Includes specific file paths and method names
- References existing code patterns and conventions
- Has concrete validation steps with actual commands
- Breaks complex work into logical phases
- Documents anti-patterns and gotchas specific to the project
- Includes risk mitigation strategies
- Has measurable success criteria
- **Has checkbox-based steps and a maintained “What else remains?” section**

Low-quality PRP plan red flags:
- Vague implementation steps
- No analysis of existing code
- Missing validation strategy
- Generic advice not specific to the project
- No anti-pattern documentation
- Lacks concrete examples and references
- No deterministic definition of “next steps”

---

## docs-mcp-server specific context

### Key files to reference

```yaml
- file: .github/copilot-instructions.md
  sections: "Core Philosophy, Definition of Done, Validation Loop"
  why: Prime directives and quality gates

- file: src/docs_mcp_server/app.py
  why: Main ASGI entry point, tenant routing

- file: src/docs_mcp_server/tenant.py
  why: Tenant factory, DDD aggregate pattern

- file: deployment.json
  why: All tenant configurations

- file: src/docs_mcp_server/search/bm25_engine.py
  why: Search ranking algorithm
````

### Validation commands

```bash
# Format and lint
uv run ruff format . && uv run ruff check --fix .

# Unit tests
timeout 60 uv run pytest -m unit --no-cov

# Integration testing
uv run python debug_multi_tenant.py --tenant <codename>

# Docker deployment
uv run python deploy_multi_tenant.py --mode online

# Docker testing
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant <codename>
```

---

## PRP plan template (copy/paste)

> This is the standard plan skeleton. Every plan must include the “Do next steps” protocol and “What else remains?” section.

```md
# <PRP Title>

## Plan Operator Contract (“Do next steps”)

When the user says **“Do next steps”** (or “yes do the next steps”):
- Always open/re-check **this plan file** first.
- “Next steps” = the **next incomplete checkbox items** in **Implementation Blueprint**, starting from the earliest incomplete phase.
- If unsure what to do next, **recheck `## What else remains?`** and resume from the topmost unfinished item.
- After you finish each chunk of work, **update this plan**:
  - Add/refresh a **Status Snapshot** entry (newest first)
  - Update checkboxes
  - Update **Blockers / Risks** and **What else remains?**
- If all items are complete:
  - Redeploy
  - Run the full validation loop (end-to-end)
  - Record results in Status Snapshot
- If items remain incomplete:
  - Implement what remains immediately
  - Stop when all items are done or when a new blocker is recorded.

## Status Snapshot (<YYYY-MM-DD>)
- (Most recent updates first; include commands run + outcomes + key metrics + blockers.)
- Example bullets:
  - ✅ …
  - ⚙️ …
  - 📊 …
  - ⛔ Blocker: …

## Goal / Why / Success Metrics
- **Goal**:
- **Why**:
- **Success metrics**:
  - [ ] Metric 1
  - [ ] Metric 2

## Current State
- Existing behavior:
- Key files:
- Dependencies:
- Constraints:
- Risks:

## Implementation Blueprint (checklist required)

### Phase 0 — Recon / alignment
- [ ] Step 0.1 — …
  - Files:
  - Notes:
  - Validation:

### Phase 1 — Core implementation
- [ ] Step 1.1 — …
- [ ] Step 1.2 — …

### Phase 2 — Tests & hardening
- [ ] Step 2.1 — …
- [ ] Step 2.2 — …

### Phase 3 — Deploy & end-to-end validation
- [ ] Step 3.1 — Redeploy
- [ ] Step 3.2 — Full validation loop
- [ ] Step 3.3 — Final status snapshot + handoff notes

## Context & Anti-Patterns
- Patterns to follow:
- Anti-patterns to avoid:
- Gotchas:

## Validation Loop
- Level 1:
- Level 2:
- Level 3:
- Level 4:

## Open Questions & Risks
- Q1:
- Risk 1:
- Mitigation:

## Plan Watchers
- **Status cadence**: update Status Snapshot after each phase completion or whenever a new blocker appears.
- **Current blockers**:
  - None / …
- **Decision log** (optional):
  - …

## What else remains?
> Keep this list in sync with the checkboxes above. This is the single source of truth for “next steps”.

- [ ] <Top unfinished item>
- [ ] …
- [ ] …
```

````


---

## File 2: `prpPlanOnly` prompt (markdown)

```md
---
name: prpPlanOnly
description: Produce a Product Requirement Prompt (PRP) plan without touching code until explicitly approved.
argument-hint: brief="one-line objective" scope="files/domains in play"
---

## TechDocs Research
Use `#techdocs` to ground every assertion. Prioritize `cosmicpython` (DDD patterns), `fastmcp`/`mcp` (tool schemas), and `github-copilot` (prompt files). Run `list_tenants` to discover additional documentation sources. Reference **.github/instructions/techdocs.instructions.md** for detailed strategies.

## Mission
- Draft or update a PRP aligned with `.github/instructions/PRP-README.md`.
- Stay in planning mode: **no code edits, migrations, config changes, or tests** until stakeholders approve.
- Apply AI-DLC planning rules so each step is explicit before execution.
- **Embed the “Do next steps” operating contract in every PRP plan** so future execution is unambiguous even if the plan is used only once.

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
