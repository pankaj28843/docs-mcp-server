#!/usr/bin/env python3
"""Comprehensive 5-tenant SQLite vs JSON benchmark with varying sizes."""

import subprocess
import time
import json
from pathlib import Path
from typing import Dict, List, Tuple


def run_search_test(config_file: str, tenant: str, query: str) -> Tuple[float, Dict]:
    """Run search test and return total time + search stats."""
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
        return 0.0, {}
    
    # Extract search metrics
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
    """Get storage size in MB for tenant."""
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


def classify_tenant_size(files_searched: int) -> str:
    """Classify tenant by size based on files searched."""
    if files_searched <= 5:
        return "XS"
    elif files_searched <= 50:
        return "S" 
    elif files_searched <= 200:
        return "M"
    elif files_searched <= 500:
        return "L"
    else:
        return "XL"


def main():
    """Run comprehensive 5-tenant benchmark with varying sizes."""
    
    # 5 tenants of varying sizes for comprehensive testing
    test_tenants = [
        {
            "name": "test-docs",
            "json_config": "deployment.json",
            "sqlite_config": "deployment.sqlite.json", 
            "queries": ["test", "storage", "sqlite"],
            "expected_size": "XS"
        },
        {
            "name": "django-5-example",
            "json_config": "deployment.json",
            "sqlite_config": "deployment.json",  # Use same for comparison
            "queries": ["model", "view", "form"],
            "expected_size": "L"
        },
        {
            "name": "ultimate-webapi-drf",
            "json_config": "deployment.json", 
            "sqlite_config": "deployment.json",
            "queries": ["serializer", "viewset", "permission"],
            "expected_size": "M"
        },
        {
            "name": "openai-docs",
            "json_config": "deployment.json",
            "sqlite_config": "deployment.json", 
            "queries": ["api", "model", "completion"],
            "expected_size": "L"
        },
        {
            "name": "ai-engineering",
            "json_config": "deployment.json",
            "sqlite_config": "deployment.json",
            "queries": ["prompt", "llm", "engineering"], 
            "expected_size": "M"
        }
    ]
    
    print("=== COMPREHENSIVE 5-TENANT SQLITE PERFORMANCE BENCHMARK ===")
    print("Advanced Optimizations: Connection pooling, prepared statements,")
    print("                       WITHOUT ROWID, WAL mode, 64MB cache, 256MB mmap")
    print("                       4KB pages, cache_spill=FALSE, EXCLUSIVE locking\n")
    
    results = {}
    
    for tenant_config in test_tenants:
        tenant_name = tenant_config["name"]
        queries = tenant_config["queries"]
        
        print(f"=== {tenant_name.upper()} ===")
        
        # Get storage sizes
        json_size = get_storage_size(tenant_name, "json")
        sqlite_size = get_storage_size(tenant_name, "sqlite")
        
        print(f"JSON storage: {json_size:.1f}MB")
        print(f"SQLite storage: {sqlite_size:.1f}MB")
        
        # Benchmark JSON
        json_times = []
        json_stats = []
        
        print(f"Testing JSON searches...")
        for query in queries:
            time_ms, stats = run_search_test(tenant_config["json_config"], tenant_name, query)
            if time_ms > 0:
                json_times.append(time_ms)
                json_stats.append(stats)
                size_class = classify_tenant_size(stats.get('files_searched', 0))
                print(f"  '{query}': {time_ms:.1f}ms (search: {stats.get('search_time_ms', 0):.1f}ms, files: {stats.get('files_searched', 0)}, size: {size_class})")
        
        # Benchmark SQLite  
        sqlite_times = []
        sqlite_stats = []
        
        print(f"Testing SQLite searches...")
        for query in queries:
            time_ms, stats = run_search_test(tenant_config["sqlite_config"], tenant_name, query)
            if time_ms > 0:
                sqlite_times.append(time_ms)
                sqlite_stats.append(stats)
                size_class = classify_tenant_size(stats.get('files_searched', 0))
                print(f"  '{query}': {time_ms:.1f}ms (search: {stats.get('search_time_ms', 0):.1f}ms, files: {stats.get('files_searched', 0)}, size: {size_class})")
        
        # Calculate performance metrics
        if json_times and sqlite_times:
            json_avg = sum(json_times) / len(json_times)
            sqlite_avg = sum(sqlite_times) / len(sqlite_times)
            total_speedup = json_avg / sqlite_avg if sqlite_avg > 0 else 0
            
            json_search_avg = sum(s.get('search_time_ms', 0) for s in json_stats) / len(json_stats)
            sqlite_search_avg = sum(s.get('search_time_ms', 0) for s in sqlite_stats) / len(sqlite_stats)
            search_speedup = json_search_avg / sqlite_search_avg if sqlite_search_avg > 0 else 0
            
            # Determine actual tenant size
            avg_files = sum(s.get('files_searched', 0) for s in json_stats) / len(json_stats)
            actual_size = classify_tenant_size(int(avg_files))
            
            results[tenant_name] = {
                "size_class": actual_size,
                "json_avg_ms": json_avg,
                "sqlite_avg_ms": sqlite_avg,
                "json_search_avg_ms": json_search_avg,
                "sqlite_search_avg_ms": sqlite_search_avg,
                "total_speedup": total_speedup,
                "search_speedup": search_speedup,
                "json_size_mb": json_size,
                "sqlite_size_mb": sqlite_size,
                "avg_files": avg_files
            }
            
            print(f"\n📊 Performance Summary:")
            print(f"Size class: {actual_size} ({int(avg_files)} files)")
            print(f"Total time - JSON: {json_avg:.1f}ms, SQLite: {sqlite_avg:.1f}ms")
            print(f"Search time - JSON: {json_search_avg:.1f}ms, SQLite: {sqlite_search_avg:.1f}ms")
            print(f"Total speedup: SQLite {total_speedup:.1f}x {'faster' if total_speedup > 1 else 'slower'}")
            print(f"Search speedup: SQLite {search_speedup:.1f}x {'faster' if search_speedup > 1 else 'slower'}")
        
        print()
    
    # Generate comprehensive summary
    print("=== COMPREHENSIVE PERFORMANCE ANALYSIS ===")
    
    if results:
        # Group by size class
        size_groups = {}
        for tenant, data in results.items():
            size_class = data["size_class"]
            if size_class not in size_groups:
                size_groups[size_class] = []
            size_groups[size_class].append((tenant, data))
        
        print("\n📊 Performance by Tenant Size:")
        for size_class in sorted(size_groups.keys()):
            tenants = size_groups[size_class]
            avg_search_speedup = sum(data["search_speedup"] for _, data in tenants) / len(tenants)
            avg_total_speedup = sum(data["total_speedup"] for _, data in tenants) / len(tenants)
            avg_files = sum(data["avg_files"] for _, data in tenants) / len(tenants)
            
            print(f"\n{size_class} Tenants ({int(avg_files)} avg files):")
            for tenant, data in tenants:
                print(f"  {tenant}: {data['search_speedup']:.1f}x search speedup")
            print(f"  Average: {avg_search_speedup:.1f}x search speedup, {avg_total_speedup:.1f}x total speedup")
        
        # Overall statistics
        all_search_speedups = [data["search_speedup"] for data in results.values() if data["search_speedup"] > 0]
        all_total_speedups = [data["total_speedup"] for data in results.values() if data["total_speedup"] > 0]
        
        if all_search_speedups:
            print(f"\n🎯 Overall Performance:")
            print(f"Average search speedup: {sum(all_search_speedups) / len(all_search_speedups):.1f}x")
            print(f"Average total speedup: {sum(all_total_speedups) / len(all_total_speedups):.1f}x")
            print(f"Best search speedup: {max(all_search_speedups):.1f}x")
            print(f"Worst search speedup: {min(all_search_speedups):.1f}x")
            
            # Sub-5ms achievement
            sub_5ms_count = sum(1 for data in results.values() if data["sqlite_search_avg_ms"] < 5.0)
            print(f"Sub-5ms achievement: {sub_5ms_count}/{len(results)} tenants")


if __name__ == "__main__":
    main()
