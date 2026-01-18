# How-To: Tune Search Ranking

**Goal**: Improve search result quality for your documentation tenants.  
**Prerequisites**: Working deployment with synced tenants, familiarity with search basics.  
**Time**: ~15-30 minutes

---

## When to Tune Search

You might need to tune search if:
- Relevant documents appear too low in results
- Irrelevant documents rank too high
- Certain document types (tutorials vs reference) should rank differently
- Search feels "off" for your documentation style

**Note**: Default BM25 parameters work well for most documentation. Only tune if you're seeing specific issues.

---

## Understanding BM25 Parameters

docs-mcp-server uses BM25 with these tunable parameters:

| Parameter | Default | Effect |
|-----------|---------|--------|
| `bm25_k1` | `1.2` | Term saturation (0.5-3.0). Higher = more weight on term frequency |
| `bm25_b` | `0.75` | Length normalization (0.1-1.0). Higher = shorter docs favored |

### k1: Term Frequency Saturation

- **Low k1 (0.5-1.0)**: Terms appearing once vs many times matter less
- **High k1 (1.5-3.0)**: Documents with many keyword occurrences rank higher
- **Use lower k1** for short docs (README, quick reference)
- **Use higher k1** for long-form content (tutorials, guides)

### b: Length Normalization

- **Low b (0.1-0.4)**: Long and short documents treated more equally
- **High b (0.7-1.0)**: Short documents boosted over long ones
- **Use lower b** if your best content is in long documents
- **Use higher b** if short, focused docs should rank first

---

## Step-by-Step Tuning

### 1. Identify the Problem

Run test queries using the debug script:

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

Review the results:
- Which documents rank 1-3?
- What are the scores?
- Are the top results actually the most relevant?

### 2. Adjust Parameters in deployment.json

Add or modify the `search` configuration for your tenant:

```json
{
  "source_type": "online",
  "codename": "drf",
  "docs_name": "Django REST Framework Docs",
  "search": {
    "ranking": {
      "bm25_k1": 1.5,
      "bm25_b": 0.6
    }
  }
}
```

### Optional ranking flags (performance trade-offs)

Phrase proximity and fuzzy matching are **disabled by default** to minimize CPU and latency. Enable them explicitly if relevance quality requires it:

```json
{
  "search": {
    "ranking": {
      "enable_phrase_bonus": true,
      "enable_fuzzy": true
    }
  }
}
```

**Tip**: Enable one at a time and re-run the search tests to confirm the quality/latency trade-off.

### 3. Redeploy and Rebuild Index

```bash
# Redeploy with new config
uv run python deploy_multi_tenant.py --mode online

# Rebuild search index
uv run python trigger_all_indexing.py --tenants drf
```

### 4. Test Again

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

Compare results to Step 1. Iterate as needed.

---

## Field Boosts

Control which parts of documents matter most:

```json
{
  "search": {
    "boosts": {
      "title": 2.5,
      "headings_h1": 2.5,
      "headings_h2": 2.0,
      "headings": 1.5,
      "body": 1.0,
      "code": 1.2,
      "path": 1.5,
      "url": 1.5
    }
  }
}
```

| Field | Default | When to Increase |
|-------|---------|------------------|
| `title` | 2.5 | Titles should dominate ranking |
| `headings_h1` | 2.5 | H1s are highly relevant |
| `headings_h2` | 2.0 | H2s contain key concepts |
| `code` | 1.2 | Code snippets are primary content |
| `path` | 1.5 | URL structure is meaningful |

**Example: Boost code snippets for API docs**:
```json
{
  "search": {
    "boosts": {
      "code": 2.0,
      "title": 2.0
    }
  }
}
```

---

## Snippet Configuration

Adjust how search snippets are generated:

```json
{
  "search": {
    "snippet": {
      "style": "plain",
      "fragment_char_limit": 240,
      "max_fragments": 2,
      "surrounding_context_chars": 120
    }
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `style` | `"plain"` | `"plain"` (brackets) or `"html"` (`<mark>` tags) |
| `fragment_char_limit` | `240` | Max characters per snippet |
| `max_fragments` | `2` | Number of snippets per result |
| `surrounding_context_chars` | `120` | Context around matched terms |

---

## Analyzer Profiles

Choose a tokenization strategy:

```json
{
  "search": {
    "analyzer_profile": "default"
  }
}
```

| Profile | Best For |
|---------|----------|
| `default` | General documentation |
| `aggressive-stem` | Documents with many word variants |
| `code-friendly` | Technical docs with code identifiers |

---

## Testing with debug_multi_tenant.py

Use the debug script for systematic testing:

```bash
# Test search with default queries from deployment.json
uv run python debug_multi_tenant.py --tenant drf --test search

# Test specific queries
uv run python debug_multi_tenant.py --tenant drf --test search --query "nested serializer"
```

### Inspect match trace diagnostics

Search responses ship lean by default—`match_stage`, `match_reason`, ripgrep flags, and performance stats are omitted from payloads.

To enable full diagnostics, set `search_include_stats` to `true` in your `deployment.json` infrastructure section:

```json
{
  "infrastructure": {
    "search_include_stats": true
  }
}
```

This single switch enables both stats and match-trace metadata across **all tenants** globally. Clients cannot toggle diagnostics per request—only infrastructure owners control this setting.

---

## Troubleshooting

### All scores are very low

**Cause**: Small corpus or common terms dominating.

**Fix**: IDF floor is automatic, but check if:
- Tenant has too few documents (< 20)
- Query terms appear in every document

### Long documents always rank first

**Cause**: b parameter too low.

**Fix**: Increase `bm25_b` to favor shorter documents:
```json
"ranking": { "bm25_b": 0.85 }
```

### Exact phrase matches don't rank high

**Cause**: BM25 is term-based, not phrase-based.

**Fix**: Phrase proximity bonuses are always enabled. If results still feel weak, try more specific query terms or confirm the content is indexed.

### Code examples not matching

**Cause**: Code tokens not indexed properly.

**Fix**: Use code-friendly analyzer and boost code field:
```json
{
  "analyzer_profile": "code-friendly",
  "boosts": { "code": 1.8 }
}
```

---

## A/B Testing Approach

To compare configurations:

1. Deploy tenant with config A
2. Run test queries, record scores
3. Deploy tenant with config B  
4. Run same queries, compare
5. Keep the better configuration

```bash
# Ensure infrastructure.search_include_stats=true in deployment.json for diagnostics

# Record baseline
curl -s "http://localhost:42042/drf/search?query=test" > baseline.json

# Change config, redeploy, rebuild index

# Compare
curl -s "http://localhost:42042/drf/search?query=test" > modified.json
diff baseline.json modified.json
```

---

## Related

- Tutorial: [Custom Search Configuration](../tutorials/custom-search.md) — Deep dive into search tuning
- Reference: [deployment.json Schema](../reference/deployment-json-schema.md) — All search options
- Explanation: [Search Ranking (BM25)](../explanations/search-ranking.md) — Why BM25 works this way
