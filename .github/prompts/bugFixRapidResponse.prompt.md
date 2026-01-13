---
name: bugFixRapidResponse
description: Minimal, surgical fix for a reported defect with focused validation.
argument-hint: file="src/docs_mcp_server/search/bm25_engine.py" repro="steps" tests="test_bm25_engine"
---

## TechDocs Research
Use `#techdocs` to verify correct API usage for the buggy component. Key tenants: `python`, `fastmcp`, `pytest`, `cosmicpython`. Always run `list_tenants` first, then `describe_tenant` to get optimal queries. See `.github/instructions/techdocs.instructions.md` for full usage guide.

## Principles
- Reproduce the bug first; capture logs or failing tests.
- Keep the diff as small as possible—no opportunistic cleanups unless they unblock the fix.
- Follow `.github/copilot-instructions.md` (Prime Directives) and `.github/instructions/validation.instructions.md` (validation loop, test requirements).

## Steps
1. **Confirm scope**: Identify exact entrypoints (MCP tool, service function, etc.) and data involved.
2. **Add/extend a failing test** (preferred) or capture the failing command output.
3. **Patch**:
   - Respect service-layer boundaries per Cosmic Python patterns.
   - Use guard clauses, clear errors, and logging aligned with existing patterns.
4. **Verify**:
   - `timeout 120 uv run pytest -m unit --no-cov -k <test_name>`
   - Any repro script originally failing.
   - `uv run ruff check <edited file>`
5. **Report**: Summarize root cause, fix, and validation commands run.

## Output
- Focused diff + brief explanation of behavioral change.
- Updated/added test demonstrating the fix.
- Follow-up items only if truly blocking (e.g., data repair, config change).
