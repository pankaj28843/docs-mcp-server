# Testing Standards - docs-mcp-server

## Testing Philosophy

### Cosmic Python Patterns
Follow Domain-Driven Design testing patterns from Architecture Patterns with Python:

- **Unit tests**: Test business logic in isolation using fakes
- **Integration tests**: Test adapters and external systems
- **End-to-end tests**: Test complete workflows

### Coverage Requirements
- **>=95% line coverage**: Enforced via pytest-cov
- **MECE tests**: Mutually Exclusive, Collectively Exhaustive
- **Behavior over implementation**: Test what code does, not how

## Unit Test Standards

### Test Structure
```python
class TestSearchService:
    """Test search service behavior."""
    
    def test_search_returns_ranked_results(self, fake_repository):
        """Test that search returns results ranked by BM25 score."""
        # Arrange
        fake_repository.add_document(Document(url="doc1", title="Python guide"))
        fake_repository.add_document(Document(url="doc2", title="Java tutorial"))
        service = SearchService(fake_repository)
        
        # Act
        results = service.search("Python")
        
        # Assert
        assert len(results) == 1
        assert results[0].url == "doc1"
        assert results[0].score > 0
```

### Fixture Patterns
```python
@pytest.fixture
def sample_schema():
    """Standard schema for testing."""
    return Schema(
        unique_field="url",
        fields=[
            TextField(name="url", stored=True, indexed=True),
            TextField(name="title", stored=True, indexed=True),
            TextField(name="body", stored=True, indexed=True),
        ]
    )

@pytest.fixture
def sample_documents():
    """Sample documents for testing."""
    return [
        {
            "url": "https://example.com/doc1",
            "title": "First Document", 
            "body": "Content about Python programming.",
        },
        {
            "url": "https://example.com/doc2",
            "title": "Second Document",
            "body": "Content about web development.",
        },
    ]
```

### Fake Objects (Cosmic Python Style)
```python
class FakeRepository:
    """Fake repository for testing."""
    
    def __init__(self):
        self._documents: dict[str, Document] = {}
    
    def add(self, document: Document) -> None:
        """Add document to fake storage."""
        self._documents[document.url.value] = document
    
    def get(self, url: str) -> Document | None:
        """Get document by URL."""
        return self._documents.get(url)
    
    def list_documents(self, limit: int = 100) -> list[Document]:
        """List all documents."""
        return list(self._documents.values())[:limit]
```

### Parametrized Tests
```python
@pytest.mark.parametrize("use_sqlite", [True, False])
def test_storage_compatibility(sample_schema, sample_documents, use_sqlite):
    """Test that both storage backends work identically."""
    if use_sqlite:
        store = SqliteSegmentStore(temp_dir)
    else:
        store = JsonSegmentStore(temp_dir)
    
    # Test identical behavior regardless of backend
    writer = SegmentWriter(sample_schema)
    for doc in sample_documents:
        writer.add_document(doc)
    
    segment = writer.build()
    store.save(segment)
    loaded = store.load(segment.segment_id)
    
    assert loaded.doc_count == len(sample_documents)
```

## Integration Test Patterns

### Database Testing
```python
def test_sqlite_storage_persistence():
    """Test SQLite storage persists data correctly."""
    with tempfile.TemporaryDirectory() as temp_dir:
        store = SqliteSegmentStore(temp_dir)
        
        # Save data
        segment_data = {"segment_id": "test", "doc_count": 5}
        db_path = store.save(segment_data)
        
        # Verify persistence by creating new store instance
        new_store = SqliteSegmentStore(temp_dir)
        loaded = new_store.load("test")
        
        assert loaded is not None
        assert loaded.doc_count == 5
```

### HTTP Client Testing
```python
@pytest.mark.asyncio
async def test_document_fetcher_handles_404():
    """Test fetcher handles missing documents gracefully."""
    async with AsyncDocFetcher() as fetcher:
        result = await fetcher.fetch_page("https://example.com/missing")
        assert result is None
```

## Test Organization

### File Structure
```
tests/
├── unit/                         # Fast, isolated tests
│   ├── test_domain_model.py     # Domain logic tests
│   ├── test_search_service.py   # Service layer tests
│   └── search/                   # Search module tests
│       ├── test_bm25_engine.py
│       └── test_sqlite_storage.py
├── integration/                  # Slower, external system tests
│   ├── test_document_fetcher.py
│   └── test_tenant_deployment.py
└── conftest.py                   # Shared fixtures
```

### Test Naming
- **Files**: `test_{module_name}.py`
- **Classes**: `Test{FeatureName}`
- **Methods**: `test_{behavior_being_tested}`

### Test Categories
```python
# Unit tests (fast, no I/O)
@pytest.mark.unit
def test_bm25_scoring_algorithm():
    """Test BM25 score calculation."""
    pass

# Integration tests (slower, real I/O)
@pytest.mark.integration  
def test_sqlite_database_operations():
    """Test actual SQLite operations."""
    pass

# End-to-end tests (slowest, full system)
@pytest.mark.e2e
def test_complete_search_workflow():
    """Test search from HTTP request to response."""
    pass
```

## Test Execution

### Running Tests
```bash
# Unit tests only (fast)
uv run pytest -m unit

# All tests with coverage
uv run pytest --cov=src --cov-report=term-missing

# Specific test file
uv run pytest tests/unit/search/test_sqlite_storage.py -v

# With timeout (prevent hanging)
timeout 60 uv run pytest -m unit
```

### Coverage Configuration
```ini
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
markers = [
    "unit: Fast unit tests",
    "integration: Integration tests", 
    "e2e: End-to-end tests",
]

[tool.coverage.run]
source = ["src"]
omit = ["*/tests/*", "*/conftest.py"]

[tool.coverage.report]
fail_under = 95
show_missing = true
```

## Anti-Patterns to Avoid

### Testing Implementation Details
```python
# BAD - tests internal method calls
def test_search_calls_tokenizer():
    """Test that search calls the tokenizer."""
    with patch('search_service.tokenizer') as mock_tokenizer:
        service.search("query")
        mock_tokenizer.assert_called_once()

# GOOD - tests behavior
def test_search_handles_empty_query():
    """Test that empty query returns no results."""
    results = service.search("")
    assert results == []
```

### Overly Complex Setup
```python
# BAD - complex test setup
def test_complex_scenario():
    """Test with too much setup."""
    # 50 lines of setup code
    # Hard to understand what's being tested
    
# GOOD - focused test with clear setup
def test_search_ranks_by_relevance(self, documents_with_scores):
    """Test that results are ranked by BM25 score."""
    results = service.search("python")
    assert results[0].score > results[1].score
```

### Silent Test Failures
```python
# BAD - catches all exceptions
def test_might_fail():
    """Test that might hide real failures."""
    try:
        risky_operation()
        assert True  # Test passes even if operation fails
    except Exception:
        pass

# GOOD - let failures surface
def test_operation_succeeds():
    """Test operation completes successfully."""
    result = risky_operation()  # Let exceptions bubble up
    assert result.is_valid()
```
