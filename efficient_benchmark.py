#!/usr/bin/env python3
"""
Efficient 81-Tenant Benchmark
PRIVATE - Do not commit to GitHub
"""

import json
import subprocess
import time
from pathlib import Path
from statistics import mean, median


def run_indexing_benchmark(config_path: str, tenant_sample: list, use_sqlite: bool) -> dict:
    """Benchmark indexing for sample tenants"""
    storage_type = "SQLite" if use_sqlite else "JSON"
    print(f"🔄 Indexing {len(tenant_sample)} tenants with {storage_type}...")
    
    # Create config
    config = json.loads(Path(config_path).read_text())
    config["infrastructure"]["search_use_sqlite"] = use_sqlite
    
    temp_config = f"/tmp/bench_{'sqlite' if use_sqlite else 'json'}.json"
    with open(temp_config, 'w') as f:
        json.dump(config, f)
    
    # Run indexing
    start_time = time.time()
    result = subprocess.run([
        "uv", "run", "python", "trigger_all_indexing.py",
        "--config", temp_config, "--tenants"] + tenant_sample,
        capture_output=True, text=True, cwd="/home/pankaj/Personal/Code/docs-mcp-server"
    )
    indexing_time = time.time() - start_time
    
    # Calculate storage sizes
    total_size = 0
    for tenant in tenant_sample:
        segments_dir = Path(f"mcp-data/{tenant}/__search_segments")
        if segments_dir.exists():
            if use_sqlite:
                db_files = list(segments_dir.glob("*.db*"))
                total_size += sum(f.stat().st_size for f in db_files)
            else:
                json_files = list(segments_dir.glob("*.json"))
                json_files = [f for f in json_files if "manifest" not in f.name]
                total_size += sum(f.stat().st_size for f in json_files)
    
    return {
        "indexing_time": indexing_time,
        "storage_size_mb": total_size / 1024 / 1024,
        "success": result.returncode == 0,
        "tenants_count": len(tenant_sample)
    }


def run_search_benchmark(config_path: str, tenant_sample: list, use_sqlite: bool) -> dict:
    """Benchmark search for sample tenants"""
    storage_type = "SQLite" if use_sqlite else "JSON"
    print(f"🔍 Testing search on {len(tenant_sample)} tenants with {storage_type}...")
    
    # Create config
    config = json.loads(Path(config_path).read_text())
    config["infrastructure"]["search_use_sqlite"] = use_sqlite
    
    temp_config = f"/tmp/search_{'sqlite' if use_sqlite else 'json'}.json"
    with open(temp_config, 'w') as f:
        json.dump(config, f)
    
    latencies = []
    successful = 0
    
    for tenant in tenant_sample:
        try:
            start = time.time()
            result = subprocess.run([
                "uv", "run", "python", "debug_multi_tenant.py",
                "--tenant", tenant, "--test", "search", "--config", temp_config
            ], capture_output=True, text=True, cwd="/home/pankaj/Personal/Code/docs-mcp-server", timeout=30)
            
            total_time = (time.time() - start) * 1000
            
            if result.returncode == 0:
                # Extract actual search time from output
                lines = result.stdout.split('\n')
                search_times = []
                for line in lines:
                    if '"search_time":' in line:
                        try:
                            time_val = float(line.split(':')[1].strip().rstrip(','))
                            search_times.append(time_val * 1000)  # Convert to ms
                        except:
                            pass
                
                if search_times:
                    latencies.extend(search_times)
                else:
                    latencies.append(total_time)
                successful += 1
                
        except subprocess.TimeoutExpired:
            print(f"  ⏰ {tenant}: timeout")
        except Exception as e:
            print(f"  ❌ {tenant}: {e}")
    
    return {
        "avg_latency_ms": mean(latencies) if latencies else 0,
        "median_latency_ms": median(latencies) if latencies else 0,
        "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
        "successful_searches": successful,
        "total_tests": len(tenant_sample),
        "all_latencies": latencies
    }


def main():
    import sys
    if len(sys.argv) != 2:
        print("Usage: python efficient_benchmark.py <deployment.json>")
        sys.exit(1)
    
    config_path = sys.argv[1]
    
    print("🚀 Efficient 81-Tenant SQLite vs JSON Benchmark")
    print("=" * 50)
    
    # Load tenant list
    config = json.loads(Path(config_path).read_text())
    all_tenants = [t["codename"] for t in config["tenants"]]
    
    # Use strategic sampling for efficiency
    sample_tenants = all_tenants[:10]  # First 10 for detailed testing
    print(f"📊 Testing {len(sample_tenants)} representative tenants: {sample_tenants}")
    
    # 1. Indexing Benchmark
    print(f"\n1️⃣ INDEXING BENCHMARK")
    print("-" * 30)
    
    json_indexing = run_indexing_benchmark(config_path, sample_tenants, use_sqlite=False)
    sqlite_indexing = run_indexing_benchmark(config_path, sample_tenants, use_sqlite=True)
    
    # 2. Search Benchmark
    print(f"\n2️⃣ SEARCH BENCHMARK")
    print("-" * 30)
    
    json_search = run_search_benchmark(config_path, sample_tenants, use_sqlite=False)
    sqlite_search = run_search_benchmark(config_path, sample_tenants, use_sqlite=True)
    
    # 3. Results Analysis
    print(f"\n📈 BENCHMARK RESULTS")
    print("=" * 50)
    
    # Storage comparison
    storage_change = ((sqlite_indexing['storage_size_mb'] - json_indexing['storage_size_mb']) / json_indexing['storage_size_mb']) * 100
    
    # Performance comparison
    latency_change = ((json_search['p95_latency_ms'] - sqlite_search['p95_latency_ms']) / json_search['p95_latency_ms']) * 100
    
    # Indexing time comparison
    indexing_change = ((json_indexing['indexing_time'] - sqlite_indexing['indexing_time']) / json_indexing['indexing_time']) * 100
    
    report = f"""
## 81-Tenant Production Benchmark Results

**Test Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}
**Sample Size**: {len(sample_tenants)} tenants
**Total Tenants Available**: {len(all_tenants)}

### Indexing Performance
- **JSON Time**: {json_indexing['indexing_time']:.1f}s
- **SQLite Time**: {sqlite_indexing['indexing_time']:.1f}s
- **Time Change**: {indexing_change:+.1f}%

### Storage Efficiency
- **JSON Size**: {json_indexing['storage_size_mb']:.1f}MB
- **SQLite Size**: {sqlite_indexing['storage_size_mb']:.1f}MB
- **Size Change**: {storage_change:+.1f}%

### Search Performance
- **JSON P95 Latency**: {json_search['p95_latency_ms']:.1f}ms
- **SQLite P95 Latency**: {sqlite_search['p95_latency_ms']:.1f}ms
- **Latency Improvement**: {latency_change:+.1f}%

### Search Success Rates
- **JSON Success**: {json_search['successful_searches']}/{json_search['total_tests']}
- **SQLite Success**: {sqlite_search['successful_searches']}/{sqlite_search['total_tests']}

### Key Findings
- **Storage**: SQLite uses {abs(storage_change):.1f}% {'more' if storage_change > 0 else 'less'} space (includes DB overhead)
- **Search Speed**: SQLite is {abs(latency_change):.1f}% {'faster' if latency_change > 0 else 'slower'}
- **Indexing**: SQLite is {abs(indexing_change):.1f}% {'faster' if indexing_change > 0 else 'slower'}

### Detailed Latencies
- **JSON**: avg={json_search['avg_latency_ms']:.1f}ms, median={json_search['median_latency_ms']:.1f}ms
- **SQLite**: avg={sqlite_search['avg_latency_ms']:.1f}ms, median={sqlite_search['median_latency_ms']:.1f}ms

### Recommendation
{'✅ SQLite shows performance benefits' if latency_change > 0 else '⚠️ JSON currently performs better'}
Storage overhead is expected due to SQLite database structure and indexes.
"""
    
    print(report)
    
    # Save results
    plan_path = "/home/pankaj/codex-prp-plans/sqlite-benchmark-80-tenants-2026-01-11T02:16:23Z.md"
    with open(plan_path, 'a') as f:
        f.write(report)
    
    print(f"📝 Results saved to: {plan_path}")


if __name__ == "__main__":
    main()
