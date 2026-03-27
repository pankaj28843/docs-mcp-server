# PRP Planning Methodology

**Product Requirement Prompt (PRP)** = PRD + codebase intelligence + agent runbook.

## When to Create a PRP Plan

Create for non-trivial tasks requiring:
- Multiple actions across several files or modules
- Complex logic needing careful analysis
- Refactoring impacting existing functionality

Skip for: single file edits, simple bug fixes, config changes.

## Plan Location

`~/codex-prp-plans/docs-mcp-server/<yyyy-mm-dd>-<slug>.md`

## "Do Next Steps" Protocol

When user says "do next steps":
1. Re-check the plan file first
2. "Next steps" = earliest incomplete checkbox items in current phase
3. After finishing work, update: Status Snapshot, checkboxes, "What else remains?"
4. If all done: run full validation loop, record results

## Required Sections

1. Goal / Why / Success Metrics
2. Current State (files, dependencies, constraints, risks)
3. Implementation Blueprint (checkbox-based phases)
4. Context & Anti-Patterns
5. Validation Loop (4 levels: syntax, unit, integration, e2e)
6. Open Questions & Risks
7. Plan Watchers (status snapshot, blockers, "What else remains?")
