# How-To: Vacuum Search Segments

**Goal**: Reclaim disk space from SQLite search segments after large deletions or body-storage changes.  
**Prerequisites**: Local checkout with `uv` installed; tenant data present under `mcp-data/`.  
**Time**: ~5 minutes.  
**What you'll learn**: How to vacuum segment DBs safely and verify the result.

## Problem

Your segment DBs keep growing after large indexing changes, and you need to reclaim disk space without changing search behavior.

## Steps

1. **Run a dry run for one tenant** to confirm the DB path:

```bash
uv run python scripts/vacuum_segments.py --dry-run --tenant mcp
```

````
Actual output from Wed Jan 14 01:25:41 PM CET 2026:
INFO:__main__:Dry run: would vacuum mcp-data/mcp/__search_segments/256fd87918ab2cb757609b1cd8157780bc7c26c1b04d216d0cf64c9f70ffd3c5.db
````

2. **Vacuum all segments for a tenant**:

```bash
uv run python scripts/vacuum_segments.py --tenant mcp
```

```
Actual output from Wed Jan 14 01:26:19 PM CET 2026:
INFO:__main__:Vacuuming mcp-data/mcp/__search_segments/256fd87918ab2cb757609b1cd8157780bc7c26c1b04d216d0cf64c9f70ffd3c5.db
```

3. **Verify the size reduction**:

```bash
du -h mcp-data/mcp/__search_segments/*.db
```

```
Actual output from Wed Jan 14 01:26:19 PM CET 2026:
11M	mcp-data/mcp/__search_segments/256fd87918ab2cb757609b1cd8157780bc7c26c1b04d216d0cf64c9f70ffd3c5.db
```

## Troubleshooting

**Symptom**: "No segment DBs found"

**Fix**: Confirm the tenant has indexed data under `mcp-data/<tenant>/__search_segments/`.

**Symptom**: Vacuum fails with `SQLITE_BUSY`

**Fix**: Stop any running search service using the same segment DB, then retry.

## Related

- Explanation: `docs/explanations/search-ranking.md`
- How-To: `docs/how-to/boot-index-audit.md`
