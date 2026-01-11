#!/usr/bin/env python3
"""Baseline performance benchmark for current architecture."""

import asyncio
import time
import tracemalloc
from pathlib import Path
import statistics
import sys

from src.docs_mcp_server.tenant import TenantApp
from src.docs_mcp_server.config import TenantConfig
from src.docs_mcp_server.deployment_config import DeploymentConfig


async def benchmark_search_latency(tenant_app: TenantApp, queries: list[str], iterations: int = 100) -> dict:
    """Benchmark search latency with current architecture."""
    latencies = []
    
    for query in queries:
        query_latencies = []
        for _ in range(iterations):
            start = time.perf_counter()
            try:
                await tenant_app.search(query, max_results=10)
                end = time.perf_counter()
                query_latencies.append((end - start) * 1000)  # Convert to ms
            except Exception as e:
                print(f"Search failed for '{query}': {e}")
                continue
        
        if query_latencies:
            latencies.extend(query_latencies)
    
    if not latencies:
        return {"error": "No successful searches"}
    
    return {
        "mean_ms": statistics.mean(latencies),
        "median_ms": statistics.median(latencies),
        "p95_ms": statistics.quantiles(latencies, n=20)[18],  # 95th percentile
        "p99_ms": statistics.quantiles(latencies, n=100)[98],  # 99th percentile
        "min_ms": min(latencies),
        "max_ms": max(latencies),
        "total_queries": len(latencies)
    }


def benchmark_memory_usage() -> dict:
    """Benchmark memory usage during tenant initialization."""
    tracemalloc.start()
    
    # Load deployment config
    config_path = Path("deployment.json")
    if not config_path.exists():
        return {"error": "deployment.json not found"}
    
    deployment_config = DeploymentConfig.from_file(config_path)
    
    # Take snapshot after config load
    snapshot1 = tracemalloc.take_snapshot()
    
    # Initialize first tenant
    tenant_configs = list(deployment_config.tenants.values())
    if not tenant_configs:
        return {"error": "No tenants in deployment.json"}
    
    tenant_app = TenantApp(tenant_configs[0])
    
    # Take snapshot after tenant init
    snapshot2 = tracemalloc.take_snapshot()
    
    # Calculate memory usage
    top_stats = snapshot2.compare_to(snapshot1, 'lineno')
    total_size = sum(stat.size for stat in top_stats)
    
    tracemalloc.stop()
    
    return {
        "tenant_init_mb": total_size / (1024 * 1024),
        "top_allocations": [
            {
                "file": str(stat.traceback.format()[-1]).split(", ")[0],
                "size_mb": stat.size / (1024 * 1024)
            }
            for stat in top_stats[:5]
        ]
    }


async def main():
    """Run baseline performance benchmarks."""
    print("🔍 Running baseline performance benchmarks...")
    
    # Memory benchmark
    print("\n📊 Memory Usage Benchmark:")
    memory_results = benchmark_memory_usage()
    if "error" in memory_results:
        print(f"❌ Memory benchmark failed: {memory_results['error']}")
        return
    
    print(f"  Tenant initialization: {memory_results['tenant_init_mb']:.2f} MB")
    print("  Top allocations:")
    for alloc in memory_results['top_allocations']:
        print(f"    {alloc['file']}: {alloc['size_mb']:.2f} MB")
    
    # Load tenant for search benchmarks
    config_path = Path("deployment.json")
    if not config_path.exists():
        print("❌ deployment.json not found")
        return
    
    deployment_config = DeploymentConfig.from_file(config_path)
    tenant_configs = list(deployment_config.tenants.values())
    if not tenant_configs:
        print("❌ No tenants in deployment.json")
        return
    
    tenant_app = TenantApp(tenant_configs[0])
    
    # Search latency benchmark
    print(f"\n⚡ Search Latency Benchmark (tenant: {tenant_configs[0].codename}):")
    test_queries = [
        "serializers",
        "authentication",
        "database models",
        "API endpoints",
        "error handling"
    ]
    
    latency_results = await benchmark_search_latency(tenant_app, test_queries, iterations=20)
    if "error" in latency_results:
        print(f"❌ Latency benchmark failed: {latency_results['error']}")
        return
    
    print(f"  Mean latency: {latency_results['mean_ms']:.2f} ms")
    print(f"  Median latency: {latency_results['median_ms']:.2f} ms")
    print(f"  95th percentile: {latency_results['p95_ms']:.2f} ms")
    print(f"  99th percentile: {latency_results['p99_ms']:.2f} ms")
    print(f"  Min/Max: {latency_results['min_ms']:.2f} / {latency_results['max_ms']:.2f} ms")
    print(f"  Total queries: {latency_results['total_queries']}")
    
    # Save results for comparison
    results = {
        "timestamp": time.time(),
        "memory": memory_results,
        "latency": latency_results
    }
    
    with open("baseline_performance.json", "w") as f:
        import json
        json.dump(results, f, indent=2)
    
    print(f"\n✅ Baseline results saved to baseline_performance.json")
    
    # Performance targets from plan
    print(f"\n🎯 Performance Targets:")
    print(f"  Target p99 latency: <10ms (current: {latency_results['p99_ms']:.2f}ms)")
    print(f"  Target memory per tenant: <50MB (current: {memory_results['tenant_init_mb']:.2f}MB)")
    
    if latency_results['p99_ms'] > 10:
        print(f"  ⚠️  Latency target missed by {latency_results['p99_ms'] - 10:.2f}ms")
    if memory_results['tenant_init_mb'] > 50:
        print(f"  ⚠️  Memory target missed by {memory_results['tenant_init_mb'] - 50:.2f}MB")


if __name__ == "__main__":
    asyncio.run(main())
