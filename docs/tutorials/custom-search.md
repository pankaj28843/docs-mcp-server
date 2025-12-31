# Tutorial: Custom Search Configuration

**Time**: ~20 minutes  
**Prerequisites**: Completed [Getting Started](getting-started.md), at least one tenant synced  
**What You'll Learn**: Configure BM25 parameters, test search quality, and optimize for your documentation

---

## Why This Matters

Default BM25 parameters work well for most documentation, but your corpus may have unique characteristics—lots of short reference pages, long tutorials, or code-heavy content. Tuning search means your AI assistant finds the right document on the first try.

---

## Overview

docs-mcp-server uses BM25 for ranking search results. While defaults work well for most documentation, you may want to tune parameters for specific use cases.

In this tutorial, you'll:
1. Understand how BM25 ranking works
2. Test your current search quality
3. Adjust parameters to improve results
4. Validate improvements with test queries

---

## Step 1: Understand Current Behavior

First, establish a baseline by running test queries:

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

Note the results:
- Which documents rank 1-3?
- What are the scores?
- Are the top results actually the most relevant?

Run 5-10 different queries (edit `test_queries` in `deployment.json`) to document which results seem "off".

---

## Step 2: Understand BM25 Parameters

BM25 has two main tuning knobs:

### k1 (Term Saturation)
Controls how much additional term occurrences matter.

- **Low (0.5-1.0)**: First occurrence of a term is most important; more occurrences add diminishing value
- **High (1.5-3.0)**: Documents with many keyword occurrences rank higher

**When to adjust**:
- Lower k1 if short documents with one mention should rank high
- Raise k1 if comprehensive documents covering a topic should rank first

### b (Length Normalization)
Controls how document length affects ranking.

- **Low (0.1-0.4)**: Long and short documents treated more equally
- **High (0.7-1.0)**: Short documents are boosted relative to long ones

**When to adjust**:
- Lower b if your best content is in detailed, long documents
- Raise b if concise docs (quick reference, cheat sheets) should rank first

---

## Step 3: Create a Test Query Set

Before changing anything, create a structured test file:

```bash
cat > search_tests.json << 'EOF'
{
  "tenant": "drf",
  "queries": [
    {
      "query": "serializer validation",
      "expected_top_3": [
        "serializers.md",
        "validation.md"
      ]
    },
    {
      "query": "viewset permissions",
      "expected_top_3": [
        "permissions.md",
        "viewsets.md"
      ]
    }
  ]
}
EOF
```

Run baseline tests using the debug script, which uses `test_queries` from your tenant config:

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

---

## Step 4: Modify Search Configuration

Edit `deployment.json` to add search configuration for your tenant:

```json
{
  "source_type": "online",
  "codename": "drf",
  "docs_name": "Django REST Framework Docs",
  "docs_sitemap_url": "https://www.django-rest-framework.org/sitemap.xml",
  "url_whitelist_prefixes": "https://www.django-rest-framework.org/",
  "docs_root_dir": "./mcp-data/drf",
  "search": {
    "ranking": {
      "bm25_k1": 1.5,
      "bm25_b": 0.6,
      "enable_proximity_bonus": true
    },
    "boosts": {
      "title": 3.0,
      "headings_h1": 2.5,
      "code": 1.5
    }
  }
}
```

**Changes made**:
- `bm25_k1: 1.5` — Slightly favor documents with more keyword occurrences
- `bm25_b: 0.6` — Reduce penalty for long documents
- `title: 3.0` — Boost title matches more heavily
- `code: 1.5` — Give more weight to code examples

---

## Step 5: Apply Changes

```bash
# Redeploy with new configuration
uv run python deploy_multi_tenant.py --mode online

# Rebuild search index (required after parameter changes)
uv run python trigger_all_indexing.py --tenants drf
```

---

## Step 6: Compare Results

Run the same test queries:

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

Compare to baseline:
- Did relevant documents move up?
- Are scores more differentiated?
- Did any good results drop?

---

## Step 7: Field Boosts Explained

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

### Boost Strategies

**For API Reference Docs**:
```json
{
  "boosts": {
    "code": 2.0,
    "title": 2.0,
    "headings_h1": 1.5
  }
}
```

**For Tutorial Content**:
```json
{
  "boosts": {
    "headings_h2": 2.5,
    "body": 1.2,
    "code": 1.0
  }
}
```

---

## Step 8: Snippet Configuration

Adjust how search result snippets appear:

```json
{
  "search": {
    "snippet": {
      "style": "plain",
      "fragment_char_limit": 300,
      "max_fragments": 3,
      "surrounding_context_chars": 150
    }
  }
}
```

Test snippet quality by running the debug script and examining the `snippet` field in results:

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

---

## Step 9: Analyzer Profiles

Choose tokenization strategy:

```json
{
  "search": {
    "analyzer_profile": "default"
  }
}
```

| Profile | Use When |
|---------|----------|
| `default` | General documentation |
| `aggressive-stem` | Many word variations (run/running/runs) |
| `code-friendly` | Technical docs with identifiers |

---

## Step 10: Validate with Test Queries

Use `test_queries` in your tenant config for automated validation:

```json
{
  "test_queries": {
    "natural": [
      "How to create a serializer",
      "Viewset permissions tutorial"
    ],
    "phrases": ["serializer", "viewset", "permission"],
    "words": ["drf", "api", "rest"]
  }
}
```

Run automated tests:

```bash
uv run python debug_multi_tenant.py --tenant drf --test search
```

---

## Verification

You should now have:
- [x] Baseline search quality documented
- [x] Custom BM25 parameters configured
- [x] Field boosts adjusted for your content type
- [x] Snippet settings optimized
- [x] Test queries validating improvements

---

## Troubleshooting

### Scores all look the same

**Cause**: Default parameters may be close to optimal.

**Fix**: Try more extreme values temporarily to see effect:
```json
{ "bm25_k1": 2.5, "bm25_b": 0.3 }
```

### Short documents always win

**Cause**: b parameter too high.

**Fix**: Lower `bm25_b` to 0.4-0.5.

### Code searches don't work well

**Cause**: Code tokens not weighted enough.

**Fix**: Use `code-friendly` analyzer and boost code:
```json
{
  "analyzer_profile": "code-friendly",
  "boosts": { "code": 2.0 }
}
```

---

## Next Steps

- How-To: [Tune Search Ranking](../how-to/tune-search.md) — Quick reference for tuning
- Explanation: [Search Ranking (BM25)](../explanations/search-ranking.md) — Deep dive into BM25
- Reference: [deployment.json Schema](../reference/deployment-json-schema.md) — All search options
