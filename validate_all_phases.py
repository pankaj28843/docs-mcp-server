#!/usr/bin/env python3
"""Comprehensive validation for all phases of performance architecture overhaul."""

import asyncio
import json
import statistics
import time
import tracemalloc
from pathlib import Path

from src.docs_mcp_server.tenant import TenantApp
from src.docs_mcp_server.simple_tenant import SimpleTenantApp
from src.docs_mcp_server.zero_dependency_tenant import ZeroDependencyTenant
from src.docs_mcp_server.deterministic_tenant import DeterministicTenant
from src.docs_mcp_server.deployment_config import DeploymentConfig


async def benchmark_implementation(impl, name: str, queries: list[str], iterations: int = 30):
    """Benchmark a specific implementation."""
    print(f"\n🔍 Benchmarking {name}...")
    
    # Memory benchmark
    tracemalloc.start()
    snapshot1 = tracemalloc.take_snapshot()
    
    # Warm up
    try:
        if hasattr(impl, 'search') and asyncio.iscoroutinefunction(impl.search):
            await impl.search("test", size=5, word_match=False)
        elif hasattr(impl, 'search'):
            impl.search("test", 5, False)
    except Exception:
        pass
    
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
                if hasattr(impl, 'search') and asyncio.iscoroutinefunction(impl.search):
                    result = await impl.search(query, size=10, word_match=False)
                elif hasattr(impl, 'search'):
                    result = impl.search(query, 10, False)
                else:
                    continue
                    
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
    """Validate all phases of the performance architecture overhaul."""
    print("🚀 Performance Architecture Overhaul - Complete Validation")
    print("=" * 70)
    
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
        "error handling"
    ]
    
    # Test all implementations
    implementations = []
    
    # Original implementation
    try:
        current_app = TenantApp(tenant_config)
        implementations.append((current_app, "Original Architecture"))
    except Exception as e:
        print(f"⚠️  Could not load original architecture: {e}")
    
    # Phase 1: Deep Module Consolidation
    try:
        phase1_app = SimpleTenantApp(tenant_config)
        implementations.append((phase1_app, "Phase 1: Deep Modules"))
    except Exception as e:
        print(f"⚠️  Could not load Phase 1: {e}")
    
    # Phase 4: Zero Dependency Injection
    try:
        phase4_app = ZeroDependencyTenant(
            tenant_config.codename, 
            f"data/{tenant_config.codename}"
        )
        implementations.append((phase4_app, "Phase 4: Zero DI"))
    except Exception as e:
        print(f"⚠️  Could not load Phase 4: {e}")
    
    # Phase 5: Deterministic Behavior
    try:
        phase5_app = DeterministicTenant(
            tenant_config.codename,
            f"data/{tenant_config.codename}"
        )
        implementations.append((phase5_app, "Phase 5: Deterministic"))
    except Exception as e:
        print(f"⚠️  Could not load Phase 5: {e}")
    
    # Benchmark all implementations
    results = []
    for impl, name in implementations:
        try:
            result = await benchmark_implementation(impl, name, test_queries, iterations=20)
            results.append(result)
            
            # Cleanup
            if hasattr(impl, 'shutdown'):
                await impl.shutdown()
            elif hasattr(impl, 'close'):
                impl.close()
        except Exception as e:
            print(f"❌ Failed to benchmark {name}: {e}")
    
    if not results:
        print("❌ No successful benchmarks")
        return
    
    # Display comparison
    print(f"\n📈 Performance Comparison:")
    print(f"{'Implementation':<25} {'Memory(MB)':<12} {'Mean(ms)':<10} {'P99(ms)':<10} {'Success%':<10}")
    print("-" * 75)
    
    baseline = None
    for result in results:
        if "error" not in result:
            if baseline is None:
                baseline = result
            
            success_rate = (result['successful_searches'] / (len(test_queries) * 20)) * 100
            print(f"{result['name']:<25} {result['memory_mb']:<12.2f} {result['mean_ms']:<10.2f} {result['p99_ms']:<10.2f} {success_rate:<10.1f}")
    
    # Target validation
    print(f"\n🎯 Target Validation:")
    for result in results:
        if "error" not in result:
            memory_ok = "✅" if result['memory_mb'] < 50 else "❌"
            latency_ok = "✅" if result['p99_ms'] < 10 else "❌"
            print(f"  {result['name']}:")
            print(f"    Memory (<50MB): {result['memory_mb']:.2f}MB {memory_ok}")
            print(f"    Latency (<10ms p99): {result['p99_ms']:.2f}ms {latency_ok}")
    
    # Calculate improvements
    if len(results) > 1 and baseline:
        print(f"\n📊 Improvements vs {baseline['name']}:")
        for result in results[1:]:
            if "error" not in result:
                memory_improvement = ((baseline['memory_mb'] - result['memory_mb']) / baseline['memory_mb']) * 100
                latency_improvement = ((baseline['mean_ms'] - result['mean_ms']) / baseline['mean_ms']) * 100
                print(f"  {result['name']}:")
                print(f"    Memory: {memory_improvement:+.1f}%")
                print(f"    Latency: {latency_improvement:+.1f}%")
    
    # Save detailed results
    with open("complete_validation_results.json", "w") as f:
        json.dump({
            "timestamp": time.time(),
            "results": results,
            "test_queries": test_queries
        }, f, indent=2)
    
    print(f"\n✅ Complete validation results saved to complete_validation_results.json")
    
    # Overall assessment
    final_result = results[-1] if results else None
    if final_result and "error" not in final_result:
        if final_result['memory_mb'] < 50 and final_result['p99_ms'] < 10:
            print(f"\n🎉 SUCCESS: All performance targets achieved!")
            print(f"   Final memory: {final_result['memory_mb']:.2f}MB")
            print(f"   Final p99 latency: {final_result['p99_ms']:.2f}ms")
        else:
            print(f"\n⚠️  PARTIAL: Some targets missed")
    else:
        print(f"\n❌ FAILED: Could not complete validation")


if __name__ == "__main__":
    asyncio.run(main())
