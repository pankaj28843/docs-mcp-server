"""
Search indexing and query engine package.

This package provides a pure-Python search stack:
- schema: Field types and schema definitions
- analyzers: Tokenizers and filters (lowercase, stop, stemming)
- storage: SQLite-based postings storage
- stats: BM25/BM25F scoring statistics
- bm25_engine: Query scoring engine
- indexer: Document indexing
"""
