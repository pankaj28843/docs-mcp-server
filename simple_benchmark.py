#!/usr/bin/env python3
"""Advanced SQLite vs JSON benchmark with multiple tenant sizes."""

import subprocess
import time
import json
from pathlib import Path


def run_search_test(config_file: str, tenant: str, query: str) -> tuple[float, dict]:
    """Run a single search test and return time in ms plus search stats."""
    start = time.perf_counter()
    
    result = subprocess.run([
        "uv", "run", "python", "debug_multi_tenant.py",
        "--tenant", tenant,
        "--test", "search",
        "--config", config_file,
        "--query", query
    ], capture_output=True, text=True, cwd="/home/pankaj/Personal/Code/docs-mcp-server")
    
    end = time.perf_counter()
    
    if result.returncode != 0:
        print(f"Error running search: {result.stderr}")
        return 0.0, {}
    
    # Extract search time from output
    search_time = 0.0
    files_searched = 0
    for line in result.stdout.split('\n'):
        if '"search_time":' in line:
            search_time = float(line.split(':')[1].strip().rstrip(','))
        elif '"files_searched":' in line:
            files_searched = int(line.split(':')[1].strip().rstrip(','))
    
    return (end - start) * 1000, {
        "search_time_ms": search_time * 1000,
        "files_searched": files_searched
    }


def get_storage_size(tenant: str, storage_type: str) -> float:
    """Get storage size in MB."""
    base_paths = [
        Path(f"/home/pankaj/Personal/Code/docs-mcp-server/data/{tenant}"),
        Path(f"/home/pankaj/Personal/Code/docs-mcp-server/mcp-data/{tenant}"),
        Path(f"/home/pankaj/Personal/Code/docs-mcp-server/{tenant}")
    ]
    
    total_size = 0
    for base_path in base_paths:
        if base_path.exists():
            if storage_type == "json":
                files = list(base_path.glob("*.json"))
            else:  # sqlite
                files = list(base_path.glob("*.db*"))
            
            total_size += sum(f.stat().st_size for f in files)
    
    return total_size / (1024 * 1024)


def main():
    """Run advanced SQLite vs JSON benchmark."""
    
    # Test with different sized tenants
    test_configs = [
        {
            "name": "Small Tenant",
            "json_tenant": "test-docs",  # Small test tenant
            "sqlite_tenant": "test-docs",
            "queries": ["test", "storage", "sqlite"]
        },
        {
            "name": "Large Tenant", 
            "json_tenant": "django-5-example",  # Larger Django docs
            "sqlite_tenant": "test-docs",  # Use test-docs for SQLite (available)
            "queries": ["model", "view", "form"]
        }
    ]
    
    print("=== Advanced SQLite Performance Optimizations Benchmark ===")
    print("Optimizations: WITHOUT ROWID, WAL mode, 64MB cache, 256MB mmap,")
    print("              4KB pages, cache_spill=FALSE, EXCLUSIVE locking, ANALYZE\n")
    
    for config in test_configs:
        print(f"=== {config['name']} ===")
        
        json_tenant = config["json_tenant"]
        sqlite_tenant = config["sqlite_tenant"]
        queries = config["queries"]
        
        # Get storage sizes
        json_size = get_storage_size(json_tenant, "json")
        sqlite_size = get_storage_size(sqlite_tenant, "sqlite")
        
        print(f"JSON storage ({json_tenant}): {json_size:.1f}MB")
        print(f"SQLite storage ({sqlite_tenant}): {sqlite_size:.1f}MB")
        
        if json_size > 0 and sqlite_size > 0:
            size_ratio = sqlite_size / json_size
            print(f"Size ratio: SQLite {size_ratio:.1f}x {'larger' if size_ratio > 1 else 'smaller'}")
        
        # Benchmark searches
        json_times = []
        sqlite_times = []
        json_stats = []
        sqlite_stats = []
        
        print(f"\nTesting JSON searches ({json_tenant})...")
        for query in queries:
            time_ms, stats = run_search_test("deployment.json", json_tenant, query)
            if time_ms > 0:
                json_times.append(time_ms)
                json_stats.append(stats)
                print(f"  '{query}': {time_ms:.1f}ms (search: {stats.get('search_time_ms', 0):.1f}ms, files: {stats.get('files_searched', 0)})")
        
        print(f"\nTesting SQLite searches ({sqlite_tenant})...")
        for query in queries:
            time_ms, stats = run_search_test("deployment.sqlite.json", sqlite_tenant, query)
            if time_ms > 0:
                sqlite_times.append(time_ms)
                sqlite_stats.append(stats)
                print(f"  '{query}': {time_ms:.1f}ms (search: {stats.get('search_time_ms', 0):.1f}ms, files: {stats.get('files_searched', 0)})")
        
        # Compare performance
        if json_times and sqlite_times:
            json_avg = sum(json_times) / len(json_times)
            sqlite_avg = sum(sqlite_times) / len(sqlite_times)
            speed_ratio = json_avg / sqlite_avg
            
            json_search_avg = sum(s.get('search_time_ms', 0) for s in json_stats) / len(json_stats)
            sqlite_search_avg = sum(s.get('search_time_ms', 0) for s in sqlite_stats) / len(sqlite_stats)
            search_speed_ratio = json_search_avg / sqlite_search_avg if sqlite_search_avg > 0 else 0
            
            print(f"\n📊 Performance Summary:")
            print(f"Total time - JSON: {json_avg:.1f}ms, SQLite: {sqlite_avg:.1f}ms")
            print(f"Search time - JSON: {json_search_avg:.1f}ms, SQLite: {sqlite_search_avg:.1f}ms")
            print(f"Total speedup: SQLite {speed_ratio:.1f}x {'faster' if speed_ratio > 1 else 'slower'}")
            print(f"Search speedup: SQLite {search_speed_ratio:.1f}x {'faster' if search_speed_ratio > 1 else 'slower'}")
        
        print()


if __name__ == "__main__":
    main()
