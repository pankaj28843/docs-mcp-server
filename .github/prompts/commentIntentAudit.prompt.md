---
title: Comment Intent Audit (Code Cleanup)
description: Systematically audit and clean code comments to remove bloat and keep only intent-explaining comments
applyTo:
  - "src/**/*.py"
---

# Comment Intent Audit Prompt

## Goal

Systematically audit all comments in a Python module and classify them as DELETE (comment noise), KEEP (explains intent), or ADD_MISSING (complex logic needs documentation).

## When to Use

- Module has accumulated comment bloat over time
- AI-generated code with verbose/obvious comments
- Refactoring module and want to clean up comments
- Before marking code "done" in a feature delivery

**For documentation file fixes, use `alignDocsSection.prompt.md` instead.**

## Comment Philosophy

From `.github/instructions/docs.instructions.md`:

**Purpose of Comments**: Explain WHY (intent, rationale, trade-offs), not WHAT (code already says that).

**DELETE These**:
- Restates what the code does
- Obvious from function/variable names
- Placeholder TODOs with no action plan
- Boilerplate docstrings that add zero value

**KEEP These**:
- Explains non-obvious intent or rationale
- Documents trade-offs or design decisions
- Known issues with context (FIXME with issue number)
- Explains why NOT doing something obvious

**ADD MISSING**:
- Complex algorithms without explanation
- Non-obvious constraints or edge cases
- Magic numbers or constants
- Important assumptions

## Instructions

You will be provided with:
1. **File path** - Python file to audit
2. **Scope** - "full file" or specific function/class name

### Step 1: Read the File

- Parse all comments (inline `#` and docstrings `"""`)
- Identify comment patterns (boilerplate, restating, intent-explaining)
- Note missing comments for complex logic

### Step 2: Classify Each Comment

Use this decision tree:

```
Does the comment explain WHY (intent/rationale)?
├─ YES → Ask: "Is the 'why' obvious from context?"
│  ├─ YES → DELETE (redundant)
│  └─ NO → KEEP (valuable intent)
└─ NO → Ask: "Does it restate WHAT the code does?"
   ├─ YES → DELETE (comment noise)
   └─ NO → Ask: "Is it a TODO/FIXME?"
      ├─ YES → Ask: "Does it have an action plan or issue #?"
      │  ├─ YES → KEEP (actionable)
      │  └─ NO → DELETE (placeholder)
      └─ NO → Probably DELETE
```

### Step 3: Identify Missing Comments

Complex logic that needs comments:

- Algorithms (BM25 scoring, tokenization)
- Performance optimizations (using set instead of list)
- Non-obvious constraints (IDF floor for small corpora)
- Magic numbers (k1=1.2, b=0.75 in BM25)
- Trade-offs (cache vs freshness)

### Step 4: Generate Audit Report

Create a structured audit with line numbers:

```markdown
# Comment Audit: src/docs_mcp_server/search/bm25_engine.py

## DELETE (Comment Noise) - 8 comments

| Line | Current Comment | Reason |
|------|----------------|--------|
| 23 | `# Increment i` | Restates `i = i + 1` |
| 45 | `# This function scores documents` | Obvious from function name `score_documents()` |
| 67 | `# TODO: Implement this` | No action plan, just noise |

## KEEP (Valuable Intent) - 5 comments

| Line | Current Comment | Why Kept |
|------|----------------|----------|
| 34 | `# IDF floor prevents negative BM25 scores in small corpora` | Explains non-obvious constraint |
| 78 | `# FIXME: Windows path separator issue (#42)` | Known issue with context |
| 102 | `# Using set for O(1) dedup instead of list (O(n))` | Explains performance trade-off |

## ADD_MISSING (Needs Comment) - 3 locations

| Line | Code | Missing Comment |
|------|------|----------------|
| 56 | `k1 = 1.2, b = 0.75` | Should explain: "BM25 params tuned for doc search" |
| 89 | Complex nested loop with multiple conditions | Should explain algorithm purpose |
| 120 | `if score < 0.01: continue` | Should explain: "Filter noise results below threshold" |

## Summary
- **Total comments**: 13
- **DELETE**: 8 (62%)
- **KEEP**: 5 (38%)
- **ADD_MISSING**: 3
- **Net change**: -5 comments (cleaner code)
```

### Step 5: Apply Changes

For each category:

**DELETE**:
```python
# Before
i = i + 1  # Increment i

# After
i = i + 1
```

**KEEP (no change)**:
```python
# IDF floor prevents negative BM25 scores in small corpora
idf = max(0.0, math.log((N - df + 0.5) / (df + 0.5) + 1))
```

**ADD_MISSING**:
```python
# Before
k1 = 1.2
b = 0.75

# After
# BM25 parameters tuned for documentation search
# k1: term frequency saturation, b: document length normalization
k1 = 1.2
b = 0.75
```

### Step 6: Validation

After cleanup:

1. **Code still works**: Run `timeout 120 uv run pytest -m unit --no-cov`
2. **Readability improved**: Ask "Can I understand this without the deleted comments?"
3. **Intent preserved**: All non-obvious decisions are still documented
4. **No type errors**: Run `get_errors` tool on modified file

## Output Format

Provide two outputs:

### 1. Audit Report (Markdown)

Use the template from Step 4 showing DELETE/KEEP/ADD_MISSING with line numbers.

### 2. Cleaned Code (File Edit)

Use `multi_replace_string_in_file` to apply all changes simultaneously:

```python
multi_replace_string_in_file(
    explanation="Remove comment noise, add missing intent comments",
    replacements=[
        {
            "filePath": "src/module.py",
            "oldString": "i = i + 1  # Increment i",
            "newString": "i = i + 1"
        },
        {
            "filePath": "src/module.py",
            "oldString": "k1 = 1.2\nb = 0.75",
            "newString": "# BM25 params: k1=term freq saturation, b=doc length norm\nk1 = 1.2\nb = 0.75"
        }
    ]
)
```

## Example Audit

### Before Cleanup

```python
"""
This module implements BM25 search.
"""

class BM25Engine:
    """BM25 search engine."""
    
    def __init__(self, documents):
        """Initialize the engine."""
        self.documents = documents  # Store documents
        self.index = {}  # Create empty index
    
    def score(self, query):
        """Score documents against query."""
        # Initialize scores
        scores = []
        
        # Loop through documents
        for doc in self.documents:
            # Calculate score
            s = self._calculate_score(doc, query)
            # Add to list
            scores.append(s)
        
        # Return scores
        return scores
```

### Audit Report

| Line | Comment | Classification | Reason |
|------|---------|---------------|--------|
| 1-3 | `"""This module implements BM25 search."""` | DELETE | Obvious from module name |
| 5 | `"""BM25 search engine."""` | DELETE | Restates class name |
| 8 | `"""Initialize the engine."""` | DELETE | Boilerplate `__init__` |
| 9 | `# Store documents` | DELETE | Restates `self.documents = documents` |
| 10 | `# Create empty index` | DELETE | Restates `self.index = {}` |
| 13 | `"""Score documents against query."""` | DELETE | Obvious from method name |
| 14 | `# Initialize scores` | DELETE | Restates `scores = []` |
| 17 | `# Loop through documents` | DELETE | Obvious from `for doc in self.documents` |
| 19 | `# Calculate score` | DELETE | Obvious from method call |
| 21 | `# Add to list` | DELETE | Obvious from `append()` |
| 24 | `# Return scores` | DELETE | Obvious from `return` |

**Missing**: Should explain BM25 algorithm or link to Wikipedia

### After Cleanup

```python
class BM25Engine:
    """
    BM25 ranking for documentation search.
    See https://en.wikipedia.org/wiki/Okapi_BM25 for algorithm details.
    """
    
    def __init__(self, documents):
        self.documents = documents
        self.index = {}
    
    def score(self, query):
        """Return BM25 scores for each document given query terms."""
        scores = []
        for doc in self.documents:
            s = self._calculate_score(doc, query)
            scores.append(s)
        return scores
```

**Result**: 11 comments deleted, 1 improved docstring with reference → Net: -10 lines, better clarity.

## Common Patterns

### Pattern 1: Boilerplate Docstrings
```python
# DELETE
def fetch_document(url):
    """Fetch a document."""
    ...

# KEEP (adds value)
def fetch_document(url):
    """Fetch document via article-extractor, falling back to raw HTML."""
    ...
```

### Pattern 2: Restating Code
```python
# DELETE
if not url:  # Check if URL is empty
    return None  # Return None

# ADD_MISSING (explain intent)
if not url:
    # Early return prevents unnecessary HTTP requests
    return None
```

### Pattern 3: TODOs
```python
# DELETE (no action plan)
# TODO: Implement this

# KEEP (actionable)
# TODO: Add retry logic for 429 rate limits (Issue #42)
```

### Pattern 4: Magic Numbers
```python
# ADD_MISSING
k1 = 1.2
b = 0.75

# After
# BM25 parameters (Terrier IR defaults for document search)
k1 = 1.2  # Term frequency saturation
b = 0.75  # Document length normalization
```

## Related Files

- `.github/instructions/docs.instructions.md` - Comment anti-bloat rules
- `.github/prompts/cleanCodeRefactor.prompt.md` - Code refactoring (includes comment cleanup step)
