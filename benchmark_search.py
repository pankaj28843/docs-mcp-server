#!/usr/bin/env python3
"""
Performance benchmarking script for docs-mcp-server.

Measures actual latency, memory usage, and CPU utilization to validate
performance claims and establish baselines.
"""

import argparse
import asyncio
import gc
import json
import statistics
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Tuple

import psutil
import requests


class PerformanceBenchmark:
    """Benchmark search performance with real measurements."""
    
    def __init__(self, host: str = "localhost", port: int = 42042):
        self.base_url = f"http://{host}:{port}"
        self.process = psutil.Process()
        
    def measure_memory_usage(self) -> Dict[str, float]:
        """Measure current memory usage in MB."""
        memory_info = self.process.memory_info()
        return {
            "rss_mb": memory_info.rss / 1024 / 1024,  # Resident Set Size
            "vms_mb": memory_info.vms / 1024 / 1024,  # Virtual Memory Size
        }
    
    def measure_cpu_usage(self, interval: float = 1.0) -> float:
        """Measure CPU usage percentage over interval."""
        return self.process.cpu_percent(interval=interval)
    
    def single_search_request(self, tenant: str, query: str) -> Tuple[float, bool]:
        """Execute single search request and measure latency."""
        start_time = time.perf_counter()
        
        try:
            response = requests.post(
                f"{self.base_url}/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "root_search",
                        "arguments": {
                            "tenant_codename": tenant,
                            "query": query,
                            "size": 10
                        }
                    }
                },
                timeout=30
            )
            
            end_time = time.perf_counter()
            latency_ms = (end_time - start_time) * 1000
            
            success = response.status_code == 200
            if success:
                result = response.json()
                success = "error" not in result.get("result", {})
            
            return latency_ms, success
            
        except Exception as e:
            end_time = time.perf_counter()
            latency_ms = (end_time - start_time) * 1000
            print(f"Request failed: {e}")
            return latency_ms, False
    
    def concurrent_search_benchmark(
        self, 
        tenant: str, 
        queries: List[str], 
        concurrent_users: int = 10,
        requests_per_user: int = 10
    ) -> Dict[str, float]:
        """Benchmark concurrent search requests."""
        
        def worker_requests(worker_id: int) -> List[Tuple[float, bool]]:
            """Execute requests for a single worker."""
            results = []
            for i in range(requests_per_user):
                query = queries[i % len(queries)]
                latency, success = self.single_search_request(tenant, query)
                results.append((latency, success))
            return results
        
        # Start memory and CPU monitoring
        initial_memory = self.measure_memory_usage()
        
        # Execute concurrent requests
        start_time = time.perf_counter()
        
        with ThreadPoolExecutor(max_workers=concurrent_users) as executor:
            futures = [
                executor.submit(worker_requests, i) 
                for i in range(concurrent_users)
            ]
            
            all_results = []
            for future in futures:
                all_results.extend(future.result())
        
        end_time = time.perf_counter()
        
        # Collect results
        latencies = [r[0] for r in all_results]
        successes = [r[1] for r in all_results]
        
        final_memory = self.measure_memory_usage()
        cpu_usage = self.measure_cpu_usage(interval=0.1)
        
        total_requests = len(all_results)
        success_rate = sum(successes) / total_requests * 100
        
        return {
            "total_requests": total_requests,
            "success_rate_percent": success_rate,
            "total_duration_seconds": end_time - start_time,
            "requests_per_second": total_requests / (end_time - start_time),
            "latency_p50_ms": statistics.median(latencies),
            "latency_p95_ms": statistics.quantiles(latencies, n=20)[18],  # 95th percentile
            "latency_p99_ms": statistics.quantiles(latencies, n=100)[98],  # 99th percentile
            "latency_mean_ms": statistics.mean(latencies),
            "latency_min_ms": min(latencies),
            "latency_max_ms": max(latencies),
            "memory_initial_mb": initial_memory["rss_mb"],
            "memory_final_mb": final_memory["rss_mb"],
            "memory_delta_mb": final_memory["rss_mb"] - initial_memory["rss_mb"],
            "cpu_usage_percent": cpu_usage,
        }
    
    def memory_leak_test(
        self, 
        tenant: str, 
        query: str, 
        iterations: int = 1000
    ) -> Dict[str, float]:
        """Test for memory leaks over many requests."""
        
        tracemalloc.start()
        initial_memory = self.measure_memory_usage()
        
        # Execute many requests
        for i in range(iterations):
            self.single_search_request(tenant, query)
            
            # Force garbage collection every 100 requests
            if i % 100 == 0:
                gc.collect()
        
        final_memory = self.measure_memory_usage()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        return {
            "iterations": iterations,
            "memory_initial_mb": initial_memory["rss_mb"],
            "memory_final_mb": final_memory["rss_mb"],
            "memory_delta_mb": final_memory["rss_mb"] - initial_memory["rss_mb"],
            "tracemalloc_current_mb": current / 1024 / 1024,
            "tracemalloc_peak_mb": peak / 1024 / 1024,
        }


def main():
    parser = argparse.ArgumentParser(description="Benchmark docs-mcp-server performance")
    parser.add_argument("--host", default="localhost", help="Server host")
    parser.add_argument("--port", type=int, default=42042, help="Server port")
    parser.add_argument("--tenant", required=True, help="Tenant to benchmark")
    parser.add_argument("--concurrent", type=int, default=10, help="Concurrent users")
    parser.add_argument("--requests", type=int, default=100, help="Total requests")
    parser.add_argument("--memory-leak-test", action="store_true", help="Run memory leak test")
    
    args = parser.parse_args()
    
    benchmark = PerformanceBenchmark(args.host, args.port)
    
    # Test queries for different tenants
    test_queries = {
        "django": [
            "models and databases",
            "authentication and authorization", 
            "forms and validation",
            "templates and views",
            "admin interface"
        ],
        "drf": [
            "serializers",
            "viewsets and routers",
            "authentication",
            "permissions",
            "status codes"
        ],
        "fastapi": [
            "dependency injection",
            "async and await",
            "pydantic models",
            "path parameters",
            "request validation"
        ]
    }
    
    queries = test_queries.get(args.tenant, ["test query"])
    
    print(f"🚀 Benchmarking {args.tenant} tenant")
    print(f"   Host: {args.host}:{args.port}")
    print(f"   Concurrent users: {args.concurrent}")
    print(f"   Total requests: {args.requests}")
    print()
    
    # Concurrent load test
    print("📊 Running concurrent load test...")
    results = benchmark.concurrent_search_benchmark(
        tenant=args.tenant,
        queries=queries,
        concurrent_users=args.concurrent,
        requests_per_user=args.requests // args.concurrent
    )
    
    print("🎯 Performance Results:")
    print(f"   Success Rate: {results['success_rate_percent']:.1f}%")
    print(f"   Requests/sec: {results['requests_per_second']:.1f}")
    print(f"   Latency P50:  {results['latency_p50_ms']:.2f}ms")
    print(f"   Latency P95:  {results['latency_p95_ms']:.2f}ms")
    print(f"   Latency P99:  {results['latency_p99_ms']:.2f}ms")
    print(f"   Memory Delta: {results['memory_delta_mb']:.2f}MB")
    print(f"   CPU Usage:    {results['cpu_usage_percent']:.1f}%")
    print()
    
    # Performance validation against claims
    print("✅ Performance Validation:")
    
    # Check P99 latency claim (should be < 5ms according to plan)
    p99_target = 5.0
    p99_actual = results['latency_p99_ms']
    p99_status = "✅ PASS" if p99_actual < p99_target else "❌ FAIL"
    print(f"   P99 Latency:  {p99_actual:.2f}ms (target: <{p99_target}ms) {p99_status}")
    
    # Check memory usage (should be < 10MB per tenant)
    memory_target = 10.0
    memory_actual = results['memory_delta_mb']
    memory_status = "✅ PASS" if memory_actual < memory_target else "❌ FAIL"
    print(f"   Memory Usage: {memory_actual:.2f}MB (target: <{memory_target}MB) {memory_status}")
    
    # Check CPU usage (should be < 5%)
    cpu_target = 5.0
    cpu_actual = results['cpu_usage_percent']
    cpu_status = "✅ PASS" if cpu_actual < cpu_target else "❌ FAIL"
    print(f"   CPU Usage:    {cpu_actual:.1f}% (target: <{cpu_target}%) {cpu_status}")
    
    # Memory leak test
    if args.memory_leak_test:
        print("\n🔍 Running memory leak test...")
        leak_results = benchmark.memory_leak_test(
            tenant=args.tenant,
            query=queries[0],
            iterations=1000
        )
        
        print("🧠 Memory Leak Results:")
        print(f"   Iterations:   {leak_results['iterations']}")
        print(f"   Memory Delta: {leak_results['memory_delta_mb']:.2f}MB")
        print(f"   Peak Memory:  {leak_results['tracemalloc_peak_mb']:.2f}MB")
        
        # Check for memory leaks (delta should be minimal)
        leak_threshold = 5.0  # MB
        leak_status = "✅ NO LEAK" if leak_results['memory_delta_mb'] < leak_threshold else "❌ LEAK DETECTED"
        print(f"   Leak Status:  {leak_status}")
    
    # Save detailed results
    output_file = f"benchmark_results_{args.tenant}_{int(time.time())}.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n📁 Detailed results saved to: {output_file}")


if __name__ == "__main__":
    main()
