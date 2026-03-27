---
name: coverage
description: Analyze test coverage gaps and add missing tests
---

## Steps
1. Run `uv run pytest -m unit --cov=src/docs_mcp_server --cov-report=term-missing` to identify uncovered lines
2. Focus on files below 95% coverage
3. Add unit tests for uncovered paths following Cosmic Python patterns (FakeUnitOfWork)
4. Test behavior, not implementation
5. Re-run coverage to verify improvement
6. Report coverage before/after
