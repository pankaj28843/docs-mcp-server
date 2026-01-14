---
name: testHardening
description: Strengthen or add tests without touching production logic.
argument-hint: target="module or behavior" focus="unit|integration|e2e"
---

## TechDocs Research
Use `#techdocs` for testing patterns, fixtures, and mocking strategies. Key tenants: `pytest`, `python`, `cosmicpython`. Always run `list_tenants` first, then `describe_tenant` to get optimal queries. See **.github/instructions/techdocs.instructions.md** for full usage guide.

## Policies
- Obey .github/instructions/tests.instructions.md (use FakeUnitOfWork for unit tests, no docstrings, `test_*` naming, prefer real objects over mocks).
- Mirror quality gates: keep helpers small, dedupe fixtures, ensure import order.

## Steps
1. **Gap analysis**: Identify behaviors missing coverage (edge cases, error paths, async flows).
2. **Test design**: Outline inputs/outputs, required factories/fixtures, and cleanup steps.
3. **Implement**:
   - Keep assertions focused on behavior (not implementation details).
   - Avoid mocking framework behavior; only mock true external dependencies.
4. **Validation**:
   - `timeout 120 uv run pytest -m unit --no-cov -k <target>`
   - Coverage check: `uv run pytest --cov=src/docs_mcp_server --cov-report=term-missing`
5. **Report**: Provide before/after coverage indicators if available, plus any remaining blind spots.

## Output
- Summary of new cases and behaviors covered.
- Commands executed.
- Noted future work if deeper coverage is still needed.
