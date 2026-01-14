---
applyTo:
  - "**/tests/**"
---

# Test Instructions (docs-mcp-server)

## General Rules

- Use `@pytest.mark.unit` for fast, isolated tests (no I/O, no network)
- Use `@pytest.mark.integration` for tests requiring real services
- Use `@pytest.mark.asyncio` for all async test functions
- Test method names start with `test_` describing behavior (e.g., `test_search_returns_positive_scores`)
- No docstrings in test classes/methods—clear method names suffice
- Avoid verbose comments; test code should be self-documenting
- Use fixtures over ad-hoc setup to reduce duplication

## Fixture Usage

```python
# Always use these fixtures in unit tests:

@pytest.fixture(autouse=True)
def clean_fake_uow():
    """Clear shared state before/after each test."""
    FakeUnitOfWork.clear_shared_store()
    yield
    FakeUnitOfWork.clear_shared_store()

@pytest.fixture
def uow_factory():
    """Factory for creating FakeUnitOfWork instances."""
    return lambda: FakeUnitOfWork()
```

## Test Behavior, Not Implementation

```python
# GOOD: Tests what the function does
async def test_search_returns_relevant_results():
    results = await search_service.search("django forms")
    assert len(results) > 0
    assert all(r.score > 0 for r in results)

# BAD: Tests how it does it
async def test_calls_bm25_engine():
    mock_engine = Mock()
    await search_service.search(..., engine=mock_engine)
    mock_engine.score.assert_called_once()  # Testing implementation
```

## Mock Only External Boundaries

```python
# GOOD: Mock external HTTP calls
with patch.object(fetcher, "_http_client") as mock_client:
    mock_client.get.return_value = mock_response
    result = await fetcher.fetch(url)

# BAD: Mock internal methods
with patch.object(service, "_internal_helper"):
    # Fragile, breaks on refactoring
```

## Test Organization

```
tests/
├── unit/  # Fast, isolated tests (NO external dependencies)
│   ├── test_bm25_engine.py      # Search engine tests
│   ├── test_repository.py       # Repository pattern tests
│   ├── test_services.py         # Service layer tests
│   └── test_*.py
├── integration/  # May use real services
│   └── test_*.py
└── conftest.py  # Shared fixtures
```

## Validation Commands

```bash
# Run unit tests (fast, <1s each)
timeout 120 uv run pytest -m unit --no-cov

# Run with coverage
uv run pytest -m unit --cov=src/docs_mcp_server --cov-report=term-missing

# Run specific test file
uv run pytest tests/unit/test_bm25_engine.py -v

# Run tests matching pattern
uv run pytest -m unit -k "test_search" --no-cov
```

## Anti-Patterns

- **No parameterized decorators** - Use loops with descriptive assertions instead
- **No fake tests** - Don't assert that constants equal literals
- **No mocking framework internals** - Only mock true external dependencies
- **No tests requiring real browsers** in unit tests - Mark as integration
- **No tests with network calls** in unit tests - Mock HTTP clients
- **No code changes without doc updates** - When test changes affect user behavior, update related docs

## Documentation Integration

When writing tests that demonstrate new features or changed behavior:

1. **Update related docs** in `docs/` to reflect the new capability
2. **Use tests as examples** - Extract test code into How-To guides or tutorials when appropriate
3. **Link from docs to tests** - Reference test file names in docs for developers who want implementation details

**Example**:
```python
# tests/unit/test_search_ranking.py
@pytest.mark.unit
async def test_english_preference_boosts_score():
    """English docs rank higher than translations (see docs/explanations/search-ranking.md)."""
    # Test implementation...
```

**Corresponding doc update**:
```markdown
<!-- docs/explanations/search-ranking.md -->
## Language Preference

English documentation receives a 1.2x score boost over translations.
This ensures primary docs rank higher than localized versions.

See `tests/unit/test_search_ranking.py::test_english_preference_boosts_score` for implementation.
```
