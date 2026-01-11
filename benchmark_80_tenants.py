#!/usr/bin/env python3
"""
80-Tenant SQLite vs JSON Storage Benchmark
PRIVATE - Do not commit to GitHub
"""

import asyncio
import json
import psutil
import time
from pathlib import Path
from statistics import mean, median
from typing import Dict, List, Tuple

from docs_mcp_server.deployment_config import DeploymentConfig


class BenchmarkResults:
    def __init__(self):
        self.json_results = {}
        self.sqlite_results = {}
        
    def record_json(self, metric: str, value: float):
        self.json_results[metric] = value
        
    def record_sqlite(self, metric: str, value: float):
        self.sqlite_results[metric] = value
        
    def improvement(self, metric: str) -> float:
        if metric in self.json_results and metric in self.sqlite_results:
            json_val = self.json_results[metric]
            sqlite_val = self.sqlite_results[metric]
            return (json_val - sqlite_val) / json_val * 100
        return 0.0


def measure_memory() -> float:
    """Get current memory usage in MB"""
    process = psutil.Process()
    return process.memory_info().rss / 1024 / 1024


def measure_directory_size(path: Path) -> int:
    """Get total size of directory in bytes"""
    total = 0
    for file_path in path.rglob('*'):
        if file_path.is_file():
            total += file_path.stat().st_size
    return total


async def benchmark_indexing(config_path: str, use_sqlite: bool) -> Dict[str, float]:
    """Benchmark indexing performance"""
    print(f"🔄 Benchmarking indexing ({'SQLite' if use_sqlite else 'JSON'})")
    
    # Load config
    config = DeploymentConfig.from_json_file(Path(config_path))
    if use_sqlite:
        config.infrastructure.search_use_sqlite = True
    else:
        config.infrastructure.search_use_sqlite = False
    
    # Save modified config
    temp_config = f"/tmp/benchmark_{'sqlite' if use_sqlite else 'json'}.json"
    with open(temp_config, 'w') as f:
        json.dump(config.model_dump(), f)
    
    # Measure indexing
    start_memory = measure_memory()
    start_time = time.time()
    
    # Run indexing for all tenants
    import subprocess
    result = subprocess.run([
        "uv", "run", "python", "trigger_all_indexing.py", 
        "--config", temp_config
    ], capture_output=True, text=True, cwd="/home/pankaj/Personal/Code/docs-mcp-server")
    
    end_time = time.time()
    end_memory = measure_memory()
    
    # Measure storage sizes
    total_size = 0
    tenant_count = 0
    for tenant in config.tenants:
        segments_dir = Path(tenant.docs_root_dir) / "__search_segments"
        if segments_dir.exists():
            total_size += measure_directory_size(segments_dir)
            tenant_count += 1
    
    return {
        "indexing_time": end_time - start_time,
        "memory_peak": end_memory - start_memory,
        "storage_size_mb": total_size / 1024 / 1024,
        "tenants_indexed": tenant_count,
        "success": result.returncode == 0
    }


async def benchmark_search_latency(config_path: str, use_sqlite: bool, sample_tenants: List[str]) -> Dict[str, float]:
    """Benchmark search latency across multiple tenants"""
    print(f"🔍 Benchmarking search ({'SQLite' if use_sqlite else 'JSON'})")
    
    # Modify config for test
    config = DeploymentConfig.from_json_file(Path(config_path))
    if use_sqlite:
        config.infrastructure.search_use_sqlite = True
    else:
        config.infrastructure.search_use_sqlite = False
    
    temp_config = f"/tmp/search_{'sqlite' if use_sqlite else 'json'}.json"
    with open(temp_config, 'w') as f:
        json.dump(config.model_dump(), f)
    
    latencies = []
    successful_searches = 0
    
    # Test search on sample tenants
    for tenant in sample_tenants[:10]:  # Test first 10 tenants
        try:
            import subprocess
            start_time = time.time()
            
            result = subprocess.run([
                "uv", "run", "python", "debug_multi_tenant.py",
                "--tenant", tenant, "--test", "search", "--config", temp_config
            ], capture_output=True, text=True, cwd="/home/pankaj/Personal/Code/docs-mcp-server")
            
            end_time = time.time()
            
            if result.returncode == 0:
                latencies.append((end_time - start_time) * 1000)  # Convert to ms
                successful_searches += 1
                
        except Exception as e:
            print(f"❌ Search failed for {tenant}: {e}")
    
    return {
        "avg_latency_ms": mean(latencies) if latencies else 0,
        "median_latency_ms": median(latencies) if latencies else 0,
        "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
        "successful_searches": successful_searches,
        "total_tests": len(sample_tenants[:10])
    }


async def benchmark_docker_deployment(config_path: str, use_sqlite: bool) -> Dict[str, float]:
    """Benchmark Docker deployment performance"""
    print(f"🐳 Benchmarking Docker ({'SQLite' if use_sqlite else 'JSON'})")
    
    # Modify config
    config = DeploymentConfig.from_json_file(Path(config_path))
    if use_sqlite:
        config.infrastructure.search_use_sqlite = True
    else:
        config.infrastructure.search_use_sqlite = False
    
    temp_config = f"/tmp/docker_{'sqlite' if use_sqlite else 'json'}.json"
    with open(temp_config, 'w') as f:
        json.dump(config.model_dump(), f)
    
    start_time = time.time()
    
    # Deploy with Docker
    import subprocess
    result = subprocess.run([
        "uv", "run", "python", "deploy_multi_tenant.py",
        "--mode", "online", "--config", temp_config
    ], capture_output=True, text=True, cwd="/home/pankaj/Personal/Code/docs-mcp-server")
    
    deploy_time = time.time() - start_time
    
    # Test server startup
    if result.returncode == 0:
        # Wait for server to be ready and test
        await asyncio.sleep(5)
        
        # Test a few searches
        search_start = time.time()
        test_result = subprocess.run([
            "curl", "-s", "http://localhost:42042/health"
        ], capture_output=True)
        search_time = time.time() - search_start
        
        # Cleanup
        subprocess.run(["docker", "stop", "docs-mcp-server"], capture_output=True)
        
        return {
            "deploy_time": deploy_time,
            "health_check_time": search_time,
            "success": test_result.returncode == 0
        }
    
    return {
        "deploy_time": deploy_time,
        "health_check_time": 0,
        "success": False
    }


async def run_comprehensive_benchmark(config_path: str) -> None:
    """Run complete benchmark suite"""
    print("🚀 Starting 80-Tenant SQLite vs JSON Benchmark")
    print("=" * 60)
    
    # Load config to get tenant list
    config = DeploymentConfig.from_json_file(Path(config_path))
    tenant_names = [t.codename for t in config.tenants]
    
    print(f"📊 Found {len(tenant_names)} tenants")
    print(f"🎯 Sample tenants: {tenant_names[:5]}...")
    
    results = BenchmarkResults()
    
    # 1. Benchmark Indexing
    print("\n1️⃣ INDEXING BENCHMARK")
    print("-" * 30)
    
    json_indexing = await benchmark_indexing(config_path, False)
    sqlite_indexing = await benchmark_indexing(config_path, True)
    
    results.record_json("indexing_time", json_indexing["indexing_time"])
    results.record_json("storage_size_mb", json_indexing["storage_size_mb"])
    results.record_sqlite("indexing_time", sqlite_indexing["indexing_time"])
    results.record_sqlite("storage_size_mb", sqlite_indexing["storage_size_mb"])
    
    # 2. Benchmark Search
    print("\n2️⃣ SEARCH BENCHMARK")
    print("-" * 30)
    
    json_search = await benchmark_search_latency(config_path, False, tenant_names)
    sqlite_search = await benchmark_search_latency(config_path, True, tenant_names)
    
    results.record_json("search_latency_p95", json_search["p95_latency_ms"])
    results.record_sqlite("search_latency_p95", sqlite_search["p95_latency_ms"])
    
    # 3. Benchmark Docker
    print("\n3️⃣ DOCKER BENCHMARK")
    print("-" * 30)
    
    json_docker = await benchmark_docker_deployment(config_path, False)
    sqlite_docker = await benchmark_docker_deployment(config_path, True)
    
    results.record_json("docker_deploy_time", json_docker["deploy_time"])
    results.record_sqlite("docker_deploy_time", sqlite_docker["deploy_time"])
    
    # 4. Generate Report
    print("\n📈 BENCHMARK RESULTS")
    print("=" * 60)
    
    report = f"""
## 80-Tenant Production Benchmark Results

**Test Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}
**Tenants**: {len(tenant_names)}

### Indexing Performance
- JSON Time: {json_indexing['indexing_time']:.2f}s
- SQLite Time: {sqlite_indexing['indexing_time']:.2f}s
- **Improvement**: {results.improvement('indexing_time'):.1f}%

### Storage Efficiency  
- JSON Size: {json_indexing['storage_size_mb']:.1f}MB
- SQLite Size: {sqlite_indexing['storage_size_mb']:.1f}MB
- **Reduction**: {results.improvement('storage_size_mb'):.1f}%

### Search Latency (p95)
- JSON: {json_search['p95_latency_ms']:.1f}ms
- SQLite: {sqlite_search['p95_latency_ms']:.1f}ms  
- **Improvement**: {results.improvement('search_latency_p95'):.1f}%

### Docker Deployment
- JSON Deploy: {json_docker['deploy_time']:.1f}s
- SQLite Deploy: {sqlite_docker['deploy_time']:.1f}s
- **Improvement**: {results.improvement('docker_deploy_time'):.1f}%

### Summary
- ✅ Storage Size Reduction: {results.improvement('storage_size_mb'):.1f}%
- ✅ Search Latency Improvement: {results.improvement('search_latency_p95'):.1f}%
- ✅ Indexing Performance: {results.improvement('indexing_time'):.1f}%
- ✅ Docker Deploy Speed: {results.improvement('docker_deploy_time'):.1f}%
"""
    
    print(report)
    
    # Save to private plan
    plan_path = "/home/pankaj/codex-prp-plans/sqlite-benchmark-80-tenants-2026-01-11T02:16:23Z.md"
    with open(plan_path, 'a') as f:
        f.write(report)
    
    print(f"📝 Results saved to: {plan_path}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python benchmark_80_tenants.py <deployment.json>")
        sys.exit(1)
    
    config_path = sys.argv[1]
    asyncio.run(run_comprehensive_benchmark(config_path))
