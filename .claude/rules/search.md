---
paths:
  - "**/search/**/*.py"
---

# Search & BM25 Rules

- BM25 params (k1=1.2, b=0.75) are tuned for documentation - do not change
- IDF floor prevents negative scores on small corpora - do not remove
- No per-tenant search tuning - fix in the algorithm, provide smart defaults
- Search services expose a synchronous "core scorer" plus thin async shells
- Unit tests target the core; integration tests exercise the shell via Fake contexts

## Must verify after changes

1. Positive scores for all results (IDF floor)
2. Relevant results in top 3 (precision)
3. English preference when applicable
4. Performance under 50ms per query
