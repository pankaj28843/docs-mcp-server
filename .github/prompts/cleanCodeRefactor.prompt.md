---
name: cleanCodeRefactor
description: Targeted renaming and structure cleanup that keeps behavior stable and intent obvious.
argument-hint: path="src/docs_mcp_server/search/" brief="optional short description"
---

## TechDocs Research
Use `#techdocs` for naming conventions, refactoring patterns, and architecture guidance. Run `list_tenants` first, then `describe_tenant` to discover available documentation sources (e.g., `cosmicpython` for DDD patterns, `python` for stdlib best practices). See `.github/instructions/techdocs.instructions.md` for full usage guide.

## When to Use
- The user asked for clearer names/structure without altering business rules.
- Documentation level is already specified in the request (default: leave module + function docstrings as-is).
- Comments should stay moderate—prefer intent-revealing identifiers over prose.

## Guardrails from Repo Rules
- Follow `.github/copilot-instructions.md`: Core Philosophy, Prime Directives, AI-Bloat Prevention
- See `.github/instructions/validation.instructions.md` for validation loop requirements
- See `.github/instructions/tests.instructions.md` for Cosmic Python test patterns
- Quality gates: keep functions <15 complexity / <120 LOC, reuse helpers.
- Keep diffs tight: avoid large-scale renames or rearrangements unless specifically requested.
- Service logic lives in services; entrypoints stay thin per Cosmic Python patterns.

## Refactor Flow
1. **Scope check**: Confirm whether the user wants docstrings/comments changed. Default to *no new module/function docstrings*.
2. **Research smartly**: Search the repo + TechDocs (`cosmicpython`, `python`) only for the patterns you need.
3. **Rename + reorganize**:
   - Replace cryptic names with full words; avoid single-letter temps.
   - Inline dead helpers; extract helpers only when they remove duplication.
   - Limit comments to business rules or tricky algorithms.
4. **Usage sweep**:
   - grep_search or editor references to update call sites, imports, and mocks.
   - Keep signatures stable unless coordinated with the user.
5. **Documentation sync**:
   - If refactor changes user-facing behavior, update related docs in `docs/`
   - Run `mkdocs build --strict` if docs changed
   - See `.github/instructions/docs.instructions.md` for standards
6. **Validation**:
   - `timeout 60 uv run pytest -m unit --no-cov` (if code paths changed).
   - `uv run ruff check <path>` for every edited file.

## Output
- Summarize renames + structural edits.
- Call out any untouched docstrings/comments if the user deferred them.
- Mention follow-up tests/commands already run (or explicitly state "not run").
