#!/usr/bin/env python3
"""Benchmark SQLite vs JSON storage performance."""

import tempfile
import time
from pathlib import Path

from docs_mcp_server.search.schema import Schema, TextField
from docs_mcp_server.search.storage import SegmentWriter
from docs_mcp_server.search.storage_factory import create_segment_store


def create_test_documents(count: int = 1000):
    """Create test documents for benchmarking."""
    documents = []
    for i in range(count):
        documents.append({
            "url": f"https://example.com/doc{i}",
            "title": f"Document {i}",
            "body": f"This is document {i} with some content to index. " * 10,
        })
    return documents


def benchmark_storage(use_sqlite: bool, documents: list, schema: Schema) -> tuple[float, float, int]:
    """Benchmark storage performance."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create segment
        writer = SegmentWriter(schema)
        for doc in documents:
            writer.add_document(doc)
        segment = writer.build()
        
        # Benchmark save
        store = create_segment_store(Path(temp_dir), use_sqlite=use_sqlite)
        
        start_time = time.time()
        db_path = store.save(segment)
        save_time = time.time() - start_time
        
        # Benchmark load
        start_time = time.time()
        loaded_segment = store.load(segment.segment_id)
        load_time = time.time() - start_time
        
        # Get file size
        file_size = db_path.stat().st_size if db_path.exists() else 0
        
        return save_time, load_time, file_size


def main():
    """Run storage benchmarks."""
    schema = Schema(
        unique_field="url",
        fields=[
            TextField(name="url", stored=True, indexed=True),
            TextField(name="title", stored=True, indexed=True),
            TextField(name="body", stored=True, indexed=True),
        ]
    )
    
    print("Creating test documents...")
    documents = create_test_documents(100)  # Start with smaller set
    
    print(f"Benchmarking with {len(documents)} documents...")
    
    # Benchmark JSON storage
    print("Testing JSON storage...")
    json_save_time, json_load_time, json_size = benchmark_storage(False, documents, schema)
    
    # Benchmark SQLite storage
    print("Testing SQLite storage...")
    sqlite_save_time, sqlite_load_time, sqlite_size = benchmark_storage(True, documents, schema)
    
    # Results
    print("\n" + "="*60)
    print("BENCHMARK RESULTS")
    print("="*60)
    print(f"Documents: {len(documents)}")
    print()
    print("JSON Storage:")
    print(f"  Save time: {json_save_time:.3f}s")
    print(f"  Load time: {json_load_time:.3f}s")
    print(f"  File size: {json_size:,} bytes")
    print()
    print("SQLite Storage:")
    print(f"  Save time: {sqlite_save_time:.3f}s")
    print(f"  Load time: {sqlite_load_time:.3f}s")
    print(f"  File size: {sqlite_size:,} bytes")
    print()
    print("Performance Comparison:")
    print(f"  Save speedup: {json_save_time/sqlite_save_time:.2f}x")
    print(f"  Load speedup: {json_load_time/sqlite_load_time:.2f}x")
    print(f"  Size reduction: {(1 - sqlite_size/json_size)*100:.1f}%")


if __name__ == "__main__":
    main()
