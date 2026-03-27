---
paths:
  - "**/tests/**"
---

# Testing Standards

- Use `@pytest.mark.unit` for fast, isolated tests (no I/O, no network)
- Use `@pytest.mark.integration` for tests requiring real services
- Use `@pytest.mark.asyncio` for all async test functions
- Test method names start with `test_` describing behavior
- No docstrings in test classes/methods - clear method names suffice
- Use FakeUnitOfWork for isolation (Cosmic Python pattern)
- Test behavior, not implementation - no mocking internal methods
- Mock only external boundaries (HTTP clients, external APIs)
- `timeout 120` prefix for all pytest commands
- Keep tests MECE (mutually exclusive, collectively exhaustive)
- >=95% line coverage enforced via pytest-cov
- No parameterized decorators - use loops with descriptive assertions
- No tests requiring real browsers in unit tests - mark as integration

## Validation

```bash
timeout 120 uv run pytest -m unit --no-cov
uv run pytest -m unit --cov=src/docs_mcp_server --cov-report=term-missing
uv run pytest tests/unit/test_bm25_engine.py -v  # specific file
```
