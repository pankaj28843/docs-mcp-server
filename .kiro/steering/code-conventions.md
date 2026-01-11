# Code Conventions - docs-mcp-server

## Core Philosophy

### Minimal Code Principle
- **Fewer lines over new layers**: Delete code whenever possible
- **No backward compatibility**: Break things freely unless explicitly requested
- **Minimal implementation**: Ship only what satisfies the requirement
- **Avoid abstraction**: Until repeated use proves necessity

### Design Patterns

#### Deep Modules, Simple Interfaces
- Module depth = functionality ÷ interface complexity
- 3+ parameter constructors signal shallow design
- Reduce to 1 parameter via context objects or smart defaults

#### Information Hiding First
- Each module encapsulates design decisions invisible to users
- If changing config requires touching 3+ files, information is leaking
- Embed decisions in context objects instead

#### Single Responsibility
- Class has ONE reason to change
- Test: describe in 25 words without "and"/"or"/"but"
- Red flags: "Manager", "Processor", "Helper", "Util" in names

## Python Style Guidelines

### Type Hints
```python
# Required for all function signatures
def build_segment(schema: Schema, documents: list[Document]) -> IndexSegment:
    """Build search segment from documents."""
    pass

# Use modern union syntax (Python 3.10+)
def load_segment(segment_id: str) -> SqliteSegment | None:
    """Load segment by ID, return None if not found."""
    pass
```

### Error Handling
```python
# Let exceptions bubble - no silent failures
def save_document(doc: Document) -> None:
    """Save document, let SQLite errors propagate."""
    with self._get_connection() as conn:
        conn.execute("INSERT INTO docs VALUES (?)", (doc.to_json(),))
        # No try/except - caller handles errors

# Domain-specific exceptions
class TenantNotFoundError(Exception):
    """Raised when tenant doesn't exist."""
    pass
```

### Context Managers
```python
# Prefer context managers for resource management
@contextmanager
def get_connection(self):
    """Get database connection from pool."""
    conn = self._pool.get()
    try:
        yield conn
    finally:
        self._pool.return_connection(conn)
```

### Data Classes and Pydantic
```python
# Use dataclasses for simple value objects
@dataclass(slots=True, frozen=True)
class SearchResult:
    """Immutable search result."""
    url: str
    title: str
    score: float

# Use Pydantic for validation and settings
class TenantConfig(BaseModel):
    """Tenant configuration with validation."""
    codename: str
    source_type: Literal["online", "git", "filesystem"]
    urls: list[str] = []
```

## Testing Conventions

### Test Structure
```python
class TestSqliteStorage:
    """Test SQLite storage functionality."""
    
    def test_saves_segment_with_metadata(self, sample_schema, sample_documents):
        """Test that segment saves with correct metadata."""
        # Arrange
        writer = SegmentWriter(sample_schema)
        for doc in sample_documents:
            writer.add_document(doc)
        
        # Act
        segment = writer.build()
        
        # Assert
        assert segment.doc_count == len(sample_documents)
```

### Fixture Patterns
```python
@pytest.fixture
def sample_schema():
    """Create test schema with common fields."""
    return Schema(
        unique_field="url",
        fields=[
            TextField(name="url", stored=True, indexed=True),
            TextField(name="title", stored=True, indexed=True),
        ]
    )
```

## Anti-Patterns to Avoid

### Verbose Comments
```python
# BAD - obvious comment
def get_document_count(self) -> int:
    """Get the number of documents."""  # Obvious from name
    return len(self.documents)

# GOOD - explains why, not what
def get_document_count(self) -> int:
    """Count used for BM25 IDF calculation."""
    return len(self.documents)
```

### Backward-Looking Comments
```python
# BAD - explains old implementation
def save_segment(self, segment: IndexSegment) -> Path:
    """Save segment to storage.
    
    Note: This used to save to JSON but now uses SQLite.
    The old format is no longer supported.
    """
    pass

# GOOD - focuses on current behavior
def save_segment(self, segment: IndexSegment) -> Path:
    """Save segment with optimized SQLite schema."""
    pass
```

### Configuration Complexity
```python
# BAD - too many configuration options
class SearchConfig:
    enable_fuzzy: bool = True
    fuzzy_distance: int = 2
    enable_stemming: bool = True
    stemmer_language: str = "english"
    enable_synonyms: bool = False
    # ... 20 more options

# GOOD - smart defaults, minimal config
class SearchConfig:
    analyzer_profile: str = "standard"  # Encapsulates all the above
```

## Refactoring Triggers

### Function Complexity
- **>15 lines**: Consider breaking into smaller functions
- **>120 lines**: Mandatory refactor
- **Multiple responsibilities**: Split by concern

### Class Complexity
- **>10 public methods**: Too many responsibilities
- **>500 lines**: Consider splitting by domain
- **Deep inheritance**: Prefer composition

### Module Coupling
- **Circular imports**: Restructure dependencies
- **>5 imports from same module**: Consider merging
- **Changes ripple to 5+ files**: Extract shared abstraction
