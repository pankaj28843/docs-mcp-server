---
name: iterativeCodeSimplification
description: Multiple fast passes to shrink logic, remove bloat, and harden resilience without obsessing over polish.
argument-hint: file="src/docs_mcp_server/search/bm25_engine.py" verify="uv run pytest -m unit --no-cov -k bm25"
---

## TechDocs Research
Use `#techdocs` for simplification techniques, async patterns, and architecture guidance. Run `list_tenants` first, then explore tenants like `python`, `cosmicpython` (for DDD patterns). Follow the workflow in **.github/instructions/techdocs.instructions.md**.

## Intent
- Reduce branching/LOC while keeping core functionality identical.
- Improve resilience by clarifying guard clauses and error handling.
- Naming/doc polish is optional; hand off to **cleanCodeRefactor** when semantics need a second pass.

## Scope Guardrails
- Default to touching only files involved in the current change; call out other opportunities in the final notes instead of editing them now.
- Preserve MCP tool schemas and API contracts unless the user explicitly includes them in scope.
- Keep async boundaries intact—don't mix sync and async helpers in the same pass.

## Working Style
1. **Snapshot**: Capture quick metrics (LOC, function count) if available.
2. **Plan tiny passes**: Each iteration targets a single idea (flatten conditionals, dedupe data conversions, share client builders, etc.).
3. **Research quickly**: Use TechDocs for best practices and reference the relevant patterns.
4. **Edit**: Apply the planned simplification using pythonic constructs, helper extraction, or early returns.
5. **Verify immediately**:
   - Run the provided `verify` command (commonly `uv run pytest -m unit --no-cov -k <area>`).
   - `uv run ruff check <file>` after the final pass.
6. **Log findings**: Note metric deltas and verification outcomes.

## Tactics
- Hoist repeated literals into constants.
- Replace nested branching with guard clauses.
- Use comprehensions/dataclasses to collapse manual loops when readability remains high.
- Drop redundant `None` checks when Pydantic validation already enforces presence.

## Validation Checklist
- Supplied `verify` command after every iteration.
- `timeout 60 uv run pytest -m unit --no-cov -k <area>` when logic paths change.
- `uv run ruff check <file>` (and `uv run ruff format <file>` if whitespace shifted).
- Record before/after LOC numbers in the working notes.

## Output
- Iteration table summarizing metric deltas, key simplifications, and verification status.
- Deferred cleanups (naming/docs) explicitly listed for follow-up prompts.
- Commands executed vs. pending clearly stated.
