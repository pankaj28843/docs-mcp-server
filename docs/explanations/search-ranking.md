# Explanation: Search Ranking (BM25)

**Audience**: Developers tuning search quality.  
**Prerequisites**: Basic IR concepts (TF/IDF, BM25).  
**What you'll learn**: Why we use BM25 with IDF floor, how snippets are generated, and when to re-index.

## Why BM25
- Handles document length normalization.
- Works well on structured documentation corpora.
- Simple to interpret and fast to compute.

## Parameters
- `k1 = 1.2`
- `b = 0.75`
- **IDF floor**: scores never go negative even on small corpora.

## Pipeline
1. Tokenize query and documents (stopwords removed).
2. Score with BM25 using precomputed term stats per segment.
3. Generate snippets around hits for context.
4. Return results with positive scores only (IDF floor).

## Verification
- Search smoke tests should return positive scores and relevant snippets (see `debug_multi_tenant.py --test search`).
- Unit tests: see `tests/unit/test_bm25_engine.py` for positive-score guarantees.

## Alternatives Considered

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| TF-IDF | Simple | Negative scores; weaker ranking | Rejected |
| Per-tenant tuning | Custom fit | Config complexity | Rejected |
| Vector search | Better semantics | Higher infra cost, slower cold start | Not needed for docs |

## When to Re-index
- After sync completes for a tenant.
- After changing scoring parameters.
- After large content additions.

Command: `uv run python trigger_all_indexing.py --tenants <tenant>` (see Reality Log Phase 2 for sample output).

