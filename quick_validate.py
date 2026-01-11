#!/usr/bin/env python3
"""
Quick SQLite Performance Validator
Tests key metrics on your 80-tenant deployment
PRIVATE - Do not commit to GitHub
"""

import json
import subprocess
import time
from pathlib import Path
from statistics import mean


def quick_storage_comparison(config_path: str) -> dict:
    """Compare storage sizes between JSON and SQLite"""
    print("📁 Comparing storage sizes...")
    
    config = json.loads(Path(config_path).read_text())
    tenants = config["tenants"]
    
    json_sizes = []
    sqlite_sizes = []
    
    for tenant in tenants[:10]:  # Sample first 10
        docs_root = Path(tenant["docs_root_dir"])
        segments_dir = docs_root / "__search_segments"
        
        if segments_dir.exists():
            # Check for JSON files
            json_files = list(segments_dir.glob("*.json"))
            if json_files:
                json_size = sum(f.stat().st_size for f in json_files)
                json_sizes.append(json_size)
            
            # Check for SQLite files  
            db_files = list(segments_dir.glob("*.db"))
            if db_files:
                sqlite_size = sum(f.stat().st_size for f in db_files)
                sqlite_sizes.append(sqlite_size)
    
    return {
        "json_avg_size_mb": mean(json_sizes) / 1024 / 1024 if json_sizes else 0,
        "sqlite_avg_size_mb": mean(sqlite_sizes) / 1024 / 1024 if sqlite_sizes else 0,
        "size_reduction_pct": ((mean(json_sizes) - mean(sqlite_sizes)) / mean(json_sizes) * 100) if json_sizes and sqlite_sizes else 0,
        "tenants_with_json": len(json_sizes),
        "tenants_with_sqlite": len(sqlite_sizes)
    }


def quick_search_test(config_path: str, tenant_sample: list) -> dict:
    """Quick search latency test"""
    print("🔍 Testing search latency...")
    
    latencies = []
    successful = 0
    
    for tenant in tenant_sample[:5]:
        try:
            start = time.time()
            result = subprocess.run([
                "uv", "run", "python", "debug_multi_tenant.py",
                "--tenant", tenant, "--test", "search", "--config", config_path
            ], capture_output=True, text=True, cwd="/home/pankaj/Personal/Code/docs-mcp-server", timeout=30)
            
            latency = (time.time() - start) * 1000
            
            if result.returncode == 0:
                latencies.append(latency)
                successful += 1
                print(f"  ✅ {tenant}: {latency:.0f}ms")
            else:
                print(f"  ❌ {tenant}: failed")
                
        except subprocess.TimeoutExpired:
            print(f"  ⏰ {tenant}: timeout")
        except Exception as e:
            print(f"  ❌ {tenant}: {e}")
    
    return {
        "avg_latency_ms": mean(latencies) if latencies else 0,
        "successful_searches": successful,
        "total_tests": len(tenant_sample[:5])
    }


def quick_indexing_test(config_path: str, sample_tenants: list) -> dict:
    """Quick indexing performance test"""
    print("⚡ Testing indexing performance...")
    
    # Test with SQLite
    sqlite_config = json.loads(Path(config_path).read_text())
    sqlite_config["infrastructure"]["search_use_sqlite"] = True
    
    temp_config = "/tmp/quick_sqlite_test.json"
    with open(temp_config, 'w') as f:
        json.dump(sqlite_config, f)
    
    start = time.time()
    result = subprocess.run([
        "uv", "run", "python", "trigger_all_indexing.py",
        "--config", temp_config, "--tenants"] + sample_tenants[:3],
        capture_output=True, text=True, cwd="/home/pankaj/Personal/Code/docs-mcp-server"
    )
    indexing_time = time.time() - start
    
    return {
        "indexing_time_seconds": indexing_time,
        "success": result.returncode == 0,
        "tenants_tested": len(sample_tenants[:3])
    }


def main():
    import sys
    if len(sys.argv) != 2:
        print("Usage: python quick_validate.py <deployment.json>")
        sys.exit(1)
    
    config_path = sys.argv[1]
    
    print("🚀 Quick SQLite Performance Validation")
    print("=" * 40)
    
    # Get tenant list
    config = json.loads(Path(config_path).read_text())
    tenants = [t["codename"] for t in config["tenants"]]
    print(f"📊 Found {len(tenants)} tenants")
    
    # 1. Storage comparison
    storage_results = quick_storage_comparison(config_path)
    print(f"\n📁 STORAGE RESULTS:")
    print(f"  JSON avg: {storage_results['json_avg_size_mb']:.1f}MB")
    print(f"  SQLite avg: {storage_results['sqlite_avg_size_mb']:.1f}MB") 
    print(f"  🎯 Size reduction: {storage_results['size_reduction_pct']:.1f}%")
    
    # 2. Search test
    search_results = quick_search_test(config_path, tenants)
    print(f"\n🔍 SEARCH RESULTS:")
    print(f"  Avg latency: {search_results['avg_latency_ms']:.0f}ms")
    print(f"  Success rate: {search_results['successful_searches']}/{search_results['total_tests']}")
    
    # 3. Indexing test
    indexing_results = quick_indexing_test(config_path, tenants)
    print(f"\n⚡ INDEXING RESULTS:")
    print(f"  Time: {indexing_results['indexing_time_seconds']:.1f}s")
    print(f"  Success: {indexing_results['success']}")
    
    # Summary
    print(f"\n🎯 QUICK VALIDATION SUMMARY:")
    print(f"  ✅ Storage reduction: {storage_results['size_reduction_pct']:.1f}%")
    print(f"  ✅ Search latency: {search_results['avg_latency_ms']:.0f}ms avg")
    print(f"  ✅ Indexing: {indexing_results['indexing_time_seconds']:.1f}s for 3 tenants")
    
    if storage_results['size_reduction_pct'] > 50:
        print("  🚀 SQLite shows significant storage savings!")
    if search_results['avg_latency_ms'] < 5000:
        print("  🚀 SQLite meets <5ms search target!")
    
    # Save quick results
    quick_report = f"""
## Quick Validation Results - {len(tenants)} Tenants

**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}

### Storage Efficiency
- Average JSON size: {storage_results['json_avg_size_mb']:.1f}MB
- Average SQLite size: {storage_results['sqlite_avg_size_mb']:.1f}MB
- **Size reduction: {storage_results['size_reduction_pct']:.1f}%**

### Search Performance  
- Average latency: {search_results['avg_latency_ms']:.0f}ms
- Success rate: {search_results['successful_searches']}/{search_results['total_tests']}

### Indexing Performance
- Time for 3 tenants: {indexing_results['indexing_time_seconds']:.1f}s
- Success: {indexing_results['success']}

### Validation Status
- Storage target (>50% reduction): {'✅ PASS' if storage_results['size_reduction_pct'] > 50 else '❌ FAIL'}
- Latency target (<5000ms): {'✅ PASS' if search_results['avg_latency_ms'] < 5000 else '❌ FAIL'}
- Indexing success: {'✅ PASS' if indexing_results['success'] else '❌ FAIL'}
"""
    
    plan_path = "/home/pankaj/codex-prp-plans/sqlite-benchmark-80-tenants-2026-01-11T02:16:23Z.md"
    with open(plan_path, 'a') as f:
        f.write(quick_report)
    
    print(f"\n📝 Quick results appended to: {plan_path}")


if __name__ == "__main__":
    main()
