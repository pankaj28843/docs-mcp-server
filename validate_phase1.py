#!/usr/bin/env python3
"""Performance comparison between current and simplified architecture."""

import asyncio
import time
import tracemalloc
from pathlib import Path
import statistics
import json

from src.docs_mcp_server.tenant import TenantApp
from src.docs_mcp_server.simple_tenant import SimpleTenantApp
from src.docs_mcp_server.deployment_config import TenantConfig, DeploymentConfig


async def benchmark_architecture(tenant_app, name: str, queries: list[str], iterations: int = 50):
    """Benchmark a specific architecture implementation."""
    print(f"\n🔍 Benchmarking {name}...")
    
    # Memory benchmark
    tracemalloc.start()
    snapshot1 = tracemalloc.take_snapshot()
    
    # Warm up
    try:
        await tenant_app.search("test query", size=5, word_match=False)
    except Exception:
        pass  # Ignore warm-up failures
    
    snapshot2 = tracemalloc.take_snapshot()
    top_stats = snapshot2.compare_to(snapshot1, 'lineno')
    memory_mb = sum(stat.size for stat in top_stats) / (1024 * 1024)
    tracemalloc.stop()
    
    # Latency benchmark
    latencies = []
    successful_searches = 0
    
    for query in queries:
        for _ in range(iterations):
            start = time.perf_counter()
            try:
                result = await tenant_app.search(query, size=10, word_match=False)
                end = time.perf_counter()
                latencies.append((end - start) * 1000)  # Convert to ms
                successful_searches += 1
            except Exception as e:
                print(f"  ⚠️  Search failed for '{query}': {e}")
                continue
    
    if not latencies:
        return {
            "name": name,
            "error": "No successful searches",
            "memory_mb": memory_mb
        }
    
    return {
        "name": name,
        "memory_mb": memory_mb,
        "successful_searches": successful_searches,
        "mean_ms": statistics.mean(latencies),
        "median_ms": statistics.median(latencies),
        "p95_ms": statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies),
        "p99_ms": statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies),
        "min_ms": min(latencies),
        "max_ms": max(latencies),
        "total_queries": len(latencies)
    }


async def main():
    """Compare current vs simplified architecture performance."""
    print("🚀 Performance Architecture Overhaul - Phase 1 Validation")
    print("=" * 60)
    
    # Load configuration
    config_path = Path("deployment.json")
    if not config_path.exists():
        print("❌ deployment.json not found")
        return
    
    deployment_config = DeploymentConfig.from_json_file(config_path)
    tenant_configs = deployment_config.tenants
    if not tenant_configs:
        print("❌ No tenants in deployment.json")
        return
    
    tenant_config = tenant_configs[0]
    print(f"📊 Testing with tenant: {tenant_config.codename}")
    
    # Test queries
    test_queries = [
        "serializers",
        "authentication", 
        "database models",
        "API endpoints",
        "error handling",
        "permissions",
        "views",
        "middleware"
    ]
    
    # Benchmark current architecture
    current_app = TenantApp(tenant_config)
    current_results = await benchmark_architecture(
        current_app, "Current Architecture", test_queries, iterations=20
    )
    
    # Benchmark simplified architecture  
    simple_app = SimpleTenantApp(tenant_config)
    simple_results = await benchmark_architecture(
        simple_app, "Simplified Architecture", test_queries, iterations=20
    )
    
    # Cleanup
    await current_app.shutdown()
    await simple_app.shutdown()
    
    # Compare results
    print(f"\n📈 Performance Comparison:")
    print(f"{'Metric':<20} {'Current':<15} {'Simplified':<15} {'Improvement':<15}")
    print("-" * 65)
    
    if "error" not in current_results and "error" not in simple_results:
        # Memory comparison
        memory_improvement = ((current_results['memory_mb'] - simple_results['memory_mb']) / current_results['memory_mb']) * 100
        print(f"{'Memory (MB)':<20} {current_results['memory_mb']:<15.2f} {simple_results['memory_mb']:<15.2f} {memory_improvement:>+13.1f}%")
        
        # Latency comparisons
        mean_improvement = ((current_results['mean_ms'] - simple_results['mean_ms']) / current_results['mean_ms']) * 100
        print(f"{'Mean Latency (ms)':<20} {current_results['mean_ms']:<15.2f} {simple_results['mean_ms']:<15.2f} {mean_improvement:>+13.1f}%")
        
        p99_improvement = ((current_results['p99_ms'] - simple_results['p99_ms']) / current_results['p99_ms']) * 100
        print(f"{'P99 Latency (ms)':<20} {current_results['p99_ms']:<15.2f} {simple_results['p99_ms']:<15.2f} {p99_improvement:>+13.1f}%")
        
        # Success rate
        current_success_rate = (current_results['successful_searches'] / (len(test_queries) * 20)) * 100
        simple_success_rate = (simple_results['successful_searches'] / (len(test_queries) * 20)) * 100
        print(f"{'Success Rate (%)':<20} {current_success_rate:<15.1f} {simple_success_rate:<15.1f} {simple_success_rate - current_success_rate:>+13.1f}%")
        
        # Target validation
        print(f"\n🎯 Target Validation:")
        print(f"  Memory target (<50MB):")
        print(f"    Current: {current_results['memory_mb']:.2f}MB {'✅' if current_results['memory_mb'] < 50 else '❌'}")
        print(f"    Simplified: {simple_results['memory_mb']:.2f}MB {'✅' if simple_results['memory_mb'] < 50 else '❌'}")
        
        print(f"  Latency target (<10ms p99):")
        print(f"    Current: {current_results['p99_ms']:.2f}ms {'✅' if current_results['p99_ms'] < 10 else '❌'}")
        print(f"    Simplified: {simple_results['p99_ms']:.2f}ms {'✅' if simple_results['p99_ms'] < 10 else '❌'}")
        
        # Save detailed results
        comparison_results = {
            "timestamp": time.time(),
            "current": current_results,
            "simplified": simple_results,
            "improvements": {
                "memory_percent": memory_improvement,
                "mean_latency_percent": mean_improvement,
                "p99_latency_percent": p99_improvement
            }
        }
        
        with open("phase1_comparison.json", "w") as f:
            json.dump(comparison_results, f, indent=2)
        
        print(f"\n✅ Detailed results saved to phase1_comparison.json")
        
        # Phase 1 success criteria
        phase1_success = (
            memory_improvement > 0 and  # Memory usage reduced
            mean_improvement > 0 and   # Mean latency improved
            simple_success_rate >= current_success_rate  # No functionality regression
        )
        
        if phase1_success:
            print(f"\n🎉 Phase 1 SUCCESS: Deep module consolidation shows improvements!")
        else:
            print(f"\n⚠️  Phase 1 needs refinement - some metrics regressed")
            
    else:
        print(f"❌ Benchmark failed:")
        if "error" in current_results:
            print(f"  Current architecture: {current_results['error']}")
        if "error" in simple_results:
            print(f"  Simplified architecture: {simple_results['error']}")


if __name__ == "__main__":
    asyncio.run(main())
