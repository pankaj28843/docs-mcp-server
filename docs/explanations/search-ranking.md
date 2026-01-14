# Explanation: Search Ranking and Indexing (BM25)

## The Problem

Documentation search must answer: "Which documents are most relevant to this query?" while staying fast and deterministic across tenants with 7 documents or 2500+ documents.

## System Overview

There are two pipelines to understand:

1. **Indexing pipeline** (builds the searchable SQLite segment)
2. **Query pipeline** (scores and returns results)

```mermaid
flowchart LR
    A[Markdown + metadata] --> B[TenantIndexer]
    B --> C[Schema + analyzers]
    C --> D[Postings + field lengths]
    D --> E[SQLite segment + manifest]
```

```mermaid
flowchart LR
    A[Query text] --> B[Analyzer]
    B --> C[Bloom filter]
    C --> D[BM25 scoring]
    D --> E[Sort + snippet]
    E --> F[Search response]
```

## Indexing Internals (fine detail)

### 1) Document discovery and inputs

`TenantIndexer` walks the tenant docs root and builds a candidate list of:
- `__docs_metadata/*.meta.json` files (when present)
- `*.md` files (Markdown)

It skips internal directories like `__docs_metadata`, `__search_segments`, `__scheduler_meta`, and VCS folders.

### 2) Document parsing and normalization

Each document becomes a **record** that includes:
- **URL**: from metadata or front matter (fallback to file URI)
- **Title**: from metadata or front matter (fallback to first heading or filename)
- **Tiered headings**: H1, H2, H3+ grouped separately for boost control
- **Excerpt**: first paragraph (truncated)
- **Tags**: from front matter
- **Language**: inferred from front matter or URL patterns (`/en/`, `/ja/`, etc.)
- **Timestamp**: metadata `last_fetched_at` or filesystem mtime

These records are the *only* source of truth for indexing, so correctness here directly impacts ranking and snippets.

### 3) Schema and fields (what gets indexed)

The default schema lives in `src/docs_mcp_server/search/schema.py` and controls:
- **Field types**: text (analyzed), keyword (exact match), numeric (sortable), stored-only
- **Boosts**: per-field weights for ranking

Key fields and intent:

| Field | Type | Indexed | Stored | Boost | Purpose |
| --- | --- | --- | --- | --- | --- |
| `url` | keyword | yes | yes | 1.0 | Unique identifier |
| `url_path` | text | yes | yes | 1.5 | Searchable URL segments |
| `title` | text | yes | yes | 2.5 | Strong relevance signal |
| `headings_h1` | text | yes | yes | 2.5 | High-weight headings |
| `headings_h2` | text | yes | yes | 2.0 | Medium-weight headings |
| `headings` | text | yes | yes | 1.5 | H3+ headings |
| `body` | text | yes | no (excerpt stored separately) | 1.0 | Full content (indexed only) |
| `path` | keyword | yes | yes | 1.5 | Filesystem path |
| `tags` | keyword | yes | yes | 1.5 | Tag matches |
| `language` | keyword | no | yes | 0.0 | Stored for filtering |
| `excerpt` | stored | no | yes | 0.0 | Snippet baseline |
| `timestamp` | numeric | yes | yes | 1.0 | Sorting/freshness |

### 4) Analyzers (tokenization and normalization)

Text fields use analyzers to convert raw text into normalized tokens:
- **Standard analyzer**: Regex tokenization, lowercasing, stopword removal, and Porter-style stemming.
- **Path analyzer**: Splits on `/` and indexes URL segments.
- **Code-friendly analyzer**: Keeps underscores and dots; no stemming (good for code docs).

The tenant can select an analyzer profile in `deployment.json` (`default`, `aggressive-stem`, `code-friendly`).

Reference: Tokenization and analyzers are implemented in `src/docs_mcp_server/search/analyzers.py`.

### 5) Postings lists and positions

Indexing builds an **inverted index** (term -> list of documents) with **positions** for each term occurrence. Positions enable phrase bonuses and better snippets. (See: [https://en.wikipedia.org/wiki/Inverted_index](https://en.wikipedia.org/wiki/Inverted_index))

`SqliteSegmentWriter.add_document()` does the heavy lifting:
- For each indexed field, it runs the analyzer.
- For each token, it appends a position to a postings list keyed by `(field, term, doc_id)`.
- It stores per-document **field lengths** to power BM25 length normalization.

### 6) Segment fingerprints and determinism

After indexing, the indexer computes a deterministic fingerprint by hashing:
- The schema definition
- Each normalized document record

This fingerprint becomes the **segment ID**. If nothing changed, the fingerprint stays stable and indexing is idempotent.

### 7) SQLite segment layout

Each segment is persisted as a single SQLite database with these tables:

- `metadata`: segment id, schema, timestamps
- `postings`: term -> doc + position blobs (WITHOUT ROWID)
- `documents`: stored fields (JSON, excerpt + metadata; full body stored on disk)
- `field_lengths`: doc length per field

The `postings` table uses **WITHOUT ROWID** to reduce storage and speed lookups for composite primary keys. (SQLite: [https://www.sqlite.org/withoutrowid.html](https://www.sqlite.org/withoutrowid.html))

SQLite pragmas applied during write:
- `journal_mode = WAL` (Write-Ahead Logging) ([https://www.sqlite.org/wal.html](https://www.sqlite.org/wal.html))
- `synchronous = NORMAL`
- `cache_size = -64000` (64MB)
- `mmap_size = 268435456` (256MB) ([https://www.sqlite.org/mmap.html](https://www.sqlite.org/mmap.html))
- `temp_store = MEMORY`
- `page_size = 4096`
- `cache_spill = FALSE`

Important SQLite constraints:
- PRAGMAs are SQLite-specific and unknown PRAGMAs are ignored silently. ([https://www.sqlite.org/pragma.html](https://www.sqlite.org/pragma.html))
- WAL creates `-wal` and `-shm` files alongside the DB for concurrency. ([https://www.sqlite.org/tempfiles.html](https://www.sqlite.org/tempfiles.html))
- Memory-mapped I/O can improve read performance but has platform-specific caveats. ([https://www.sqlite.org/mmap.html](https://www.sqlite.org/mmap.html))

### 8) Segment manifest and pruning

A `manifest.json` in the `__search_segments` directory points to the latest segment id and doc count. When a new segment is saved, older segments are pruned to keep storage bounded.

## Query-Time Ranking (BM25)

### 1) Query analysis

The query string is tokenized with the standard analyzer (lowercase, stopwords, stemming). The same analyzer family is used for most text fields to keep query and index normalization consistent.

### 2) Bloom filter pre-check

If enabled, a bloom filter quickly checks whether a query term might exist in the vocabulary. Terms that are definitely absent are dropped, which saves work. ([Bloom filter](https://en.wikipedia.org/wiki/Bloom_filter))

This is a **probabilistic** optimization: it can return false positives, but never false negatives.

### 3) BM25 scoring

The core ranking uses BM25. ([BM25 overview](https://en.wikipedia.org/wiki/Okapi_BM25))

Simplified scoring per term (SegmentSearchIndex path):

```
score = idf(term) * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * docLen/avgLen))
```

Notes:
- `idf(term)` is computed as `log((N - df + 0.5) / (df + 0.5))` in `SegmentSearchIndex`.
- If a term appears in most documents, this IDF can be negative; scores can go below zero and are still sorted by score.
- Document length comes from the `field_lengths` table; if missing, we fall back to the average length.

### 4) Sorting and snippets

Documents are sorted by total score and the top N are returned. Snippets are generated by locating query tokens in the document body; the body is read from disk using the stored `path` field, with the stored `excerpt` as a fallback.

## Optimizations and Fast Paths

### Bloom filter vocabulary filter

- Built from distinct terms in `postings` (capped for size control).
- Filters query terms before scoring.
- Best for reducing work on low-quality or noisy queries.

### SIMD vectorization (NumPy)

SIMD (Single Instruction, Multiple Data) speeds up vector math by processing multiple numbers per instruction. ([SIMD](https://en.wikipedia.org/wiki/SIMD))

The SIMD path:
- Uses NumPy vectorization to compute BM25 scores for multiple terms at once.
- Falls back to scalar computation on small data or if vectorization fails.

### Lock-free concurrency

The lock-free path uses thread-local SQLite connections and WAL mode to reduce lock contention under concurrent reads. It is optimized for read-heavy workloads and keeps queries in `query_only` mode for safety.

## SQLite Performance Trade-offs (Why these PRAGMAs)

- **WAL**: improves read/write concurrency and sequential I/O but requires shared memory and same-host access. ([https://www.sqlite.org/wal.html](https://www.sqlite.org/wal.html))
- **mmap_size**: can reduce CPU and memory copies for reads, but can be unsafe on some platforms and is disabled by default in SQLite. ([https://www.sqlite.org/mmap.html](https://www.sqlite.org/mmap.html))
- **temp_store = MEMORY**: avoids disk temp files for transient data but uses RAM. ([https://www.sqlite.org/tempfiles.html](https://www.sqlite.org/tempfiles.html))
- **query_only = 1** (search runtime): guards against accidental writes during query execution.

## Observability (OpenTelemetry-aligned)

Search uses OpenTelemetry-style tracing and metrics in `src/docs_mcp_server/observability/`.

- **Trace span**: `search.query` (search execution) and `http.request` (request boundary).
- **Span attributes**: `search.query`, `search.max_results`, `search.result_count`.
- **Metrics**: `search_latency_seconds` histogram and request/error counters.
- **Logs**: structured JSON with `trace_id` and `span_id` for correlation.

Use these signals to confirm low latency, low error rates, and stable indexing throughput without increasing label cardinality.

## When to Re-index

Rebuild a segment when:
- A tenant sync completes (new docs on disk)
- Schema or ranking parameters change
- A large content update occurs (roughly >10% new documents)

## Alternatives Considered

| Approach | Pros | Cons | Decision |
| --- | --- | --- | --- |
| TF-IDF | Simple implementation | Negative scores on small corpora; weaker ranking | Rejected |
| Per-tenant tuning | Custom fit per corpus | Configuration complexity; harder to maintain | Rejected |
| Vector search | Semantic relevance | Higher infra cost; slower cold starts | Not needed for keyword docs |
| Hybrid (BM25 + vectors) | Best of both worlds | Complexity; diminishing returns for docs | Future consideration |

## Further Reading

- [BM25](https://en.wikipedia.org/wiki/Okapi_BM25)
- [Inverted index](https://en.wikipedia.org/wiki/Inverted_index)
- [Bloom filter](https://en.wikipedia.org/wiki/Bloom_filter)
- [SIMD](https://en.wikipedia.org/wiki/SIMD)
- [SQLite WAL](https://www.sqlite.org/wal.html)
- [SQLite mmap](https://www.sqlite.org/mmap.html)
- [SQLite PRAGMA](https://www.sqlite.org/pragma.html)
- [SQLite temp files](https://www.sqlite.org/tempfiles.html)
- [SQLite WITHOUT ROWID](https://www.sqlite.org/withoutrowid.html)
- [Architecture](architecture.md)
