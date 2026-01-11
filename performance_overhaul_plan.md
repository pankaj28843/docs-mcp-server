# Performance Overhaul Plan

## Context
Based on the benchmark run on Jan 11, 2026, the current system performance (P95) is:
- **Direct Search:** ~33ms
- **MCP Search:** ~79ms
- **MCP Overhead:** ~46ms (Search), ~12ms (Fetch)

**Goal:** Reduce MCP search latency to < 50ms and Direct search to < 20ms.

## Analysis
The significant overhead in MCP search suggests costs associated with serialization, Pydantic validation, or protocol handling. The direct search time, while acceptable, is CPU-bound in Python and can be optimized.

## Strategic Initiatives

### 1. Serialization Optimization (High Impact)
The `storage.py` module attempts to import `orjson` but falls back to `json`.
- **Action:** Ensure `orjson` is strictly required and installed.
- **Rationale:** `orjson` is 2-5x faster than `json` for serialization/deserialization, which directly impacts the MCP overhead and index loading time.

### 2. Search Algorithm Optimization (`bm25_engine.py`)
The current BM25 implementation performs a full scan of all documents containing any query term.
- **Action:** Implement **WAND (Weak AND)** or **Block-Max WAND** logic to skip scoring documents that cannot possibly make the top-K results.
- **Action:** Optimize the inner scoring loop by reducing function calls and dictionary lookups.
- **Action:** Pre-compute IDFs and other constant factors at index load time.

### 3. Caching Strategy
- **Action:** Implement a short-lived (TTL) **Result Cache** for `search` operations. Identical queries within a short window (e.g., 5s) should be served instantly.
- **Action:** Verify `IndexSegment` in-memory persistence. Ensure segments are not being reloaded from disk unnecessarily.

### 4. Protocol & Payload Tuning
- **Action:** Review the `root_search` tool output. Ensure we are not sending excessive data (like full body text) in the search result list unless requested. Truncate snippets efficiently.
- **Action:** Profile `fastmcp` integration to identify validation bottlenecks.

### 5. Asynchronous Concurrency
- **Action:** The search logic is CPU-bound. For high-concurrency scenarios, offload the synchronous `score` method to a thread pool to avoid blocking the `asyncio` event loop.

## Execution Plan
1.  **Dependency:** Add `orjson` to `pyproject.toml` if missing.
2.  **Profile:** Run `cProfile` on `bench_mcp_overhead.py` to identify the hottest lines.
3.  **Refactor:** Apply `bm25_engine` optimizations.
4.  **Verify:** Re-run benchmarks to validate improvements.
