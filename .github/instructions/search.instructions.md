---
applyTo: **/search/**/*.py
---

# Search & BM25 Instructions (docs-mcp-server)

## Architecture Overview

The search system uses a multi-stage pipeline:
1. **Query preprocessing** - Tokenization, stemming, stop word removal
2. **BM25 scoring** - Term frequency and inverse document frequency
3. **Snippet generation** - Extract relevant text fragments
4. **Result ranking** - Final score with optional boosts

## Key Files

- `src/docs_mcp_server/search/bm25_engine.py` - Core BM25 implementation
- `src/docs_mcp_server/search/indexer.py` - Document indexing
- `src/docs_mcp_server/search/snippet.py` - Snippet extraction
- `src/docs_mcp_server/search/schema.py` - Search result schema

## BM25 Parameters

```python
# Default BM25 parameters (tuned for documentation)
k1 = 1.2   # Term frequency saturation
b = 0.75  # Document length normalization
```

## Smart Defaults Philosophy

- **No per-tenant tuning** - BM25 params work across all tenants
- **IDF floor** - Prevents negative scores on small corpora
- **English preference** - Auto-detected from URL patterns
- **Graceful degradation** - Works for 7 docs or 2500 docs

## Testing Search Changes

Always write tests that verify:
1. Positive scores for all results (IDF floor)
2. Relevant results in top 3 (precision)
3. English preference when applicable
4. Performance under 50ms per query

```python
@pytest.mark.unit
async def test_search_returns_positive_scores():
    engine = BM25Engine(documents)
    results = engine.search("django forms")
    assert all(r.score > 0 for r in results)
```

## Validation Loop

```bash
# 1. Run search-specific unit tests
uv run pytest tests/unit/test_bm25_engine.py -v

# 2. Run full unit test suite
timeout 60 uv run pytest -m unit --no-cov

# 3. Test with real data
uv run python debug_multi_tenant.py --tenant django --test search
```

## Anti-Patterns

- **Don't add per-tenant config** - Fix in the algorithm instead
- **Don't tune BM25 params** - They're already optimized
- **Don't skip snippet generation** - Users need context
- **Don't ignore edge cases** - Small corpora, short queries, etc.
- **Don't skip docs** - Update `docs/explanations/search-ranking.md` when changing scoring logic

## Documentation Requirements

When changing search/ranking behavior:

1. **Update Explanation doc**: `docs/explanations/search-ranking.md` - Explain WHY the change improves results
2. **Add How-To if needed**: `docs/how-to/tune-search.md` - If users can configure/adjust the feature
3. **Update tests**: Reference doc location in test docstrings

**Example**:
```python
# After implementing IDF floor
@pytest.mark.unit
async def test_idf_floor_prevents_negative_scores():
    """IDF floor ensures positive BM25 scores. See docs/explanations/search-ranking.md#idf-floor."""
    # Test implementation...
```

**Then update `docs/explanations/search-ranking.md`**:
```markdown
## IDF Floor

Small document collections (<100 docs) can produce negative IDF values for common terms.
We apply an IDF floor of 0.0 to ensure all BM25 scores are positive.

### Implementation
See `src/docs_mcp_server/search/bm25_engine.py` and test `tests/unit/test_bm25_engine.py::test_idf_floor_prevents_negative_scores`.
```
