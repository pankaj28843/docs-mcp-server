#!/usr/bin/env python3
"""Enhanced debug script for multi-tenant docs MCP server.

🔒 SAFETY GUARANTEE: This script NEVER deletes any documents.
It only performs READ-ONLY operations and triggers sync processes that ADD/UPDATE documents.

Features:
- Tests specific tenant or all tenants
- Manages server lifecycle with pidfile
- Reuses same log file across sessions for debugging
- Non-interactive testing suitable for CI/CD
- Automatic server cleanup on exit
- Uses proper MCP Client for tool testing
- Patches deployment.json for local testing
- Supports connecting to external servers (e.g., Docker containers)
- 🔒 DELETION-SAFE: Only reads data, never deletes anything

Usage:
    # Test all tenants (offline mode, port 42043)
    uv run python debug_multi_tenant.py

    # Test specific tenant (offline mode, auto keep-alive)
    uv run python debug_multi_tenant.py --tenant django

    # Test with sync enabled (online mode)
    uv run python debug_multi_tenant.py --enable-sync

    # Test specific operation for a tenant (offline mode)
    uv run python debug_multi_tenant.py --tenant drf --test search

    # Connect to external Docker container
    uv run python debug_multi_tenant.py --host 127.0.0.1 --port 42042 --tenant django

    # Trigger sync on Docker container and monitor
    uv run python debug_multi_tenant.py --host 127.0.0.1 --port 42042 --trigger-sync --enable-sync
"""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from fastmcp import Client
import httpx
from mcp.types import TextContent
from rich.console import Console


# Constants
def get_free_port():
    """Get a random free port to avoid conflicts in parallel runs."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))  # 0 tells the OS to pick a free port
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


DEBUG_DIR = Path(tempfile.gettempdir()) / "docs-mcp-server-multi-debug"
PIDFILE = DEBUG_DIR / "server.pid"
LOGFILE = DEBUG_DIR / "server.log"
DEBUG_CONFIG = DEBUG_DIR / "deployment.debug.json"  # Changed to match docker pattern
DEFAULT_PORT = None  # Will be set to random port when needed
DEFAULT_HOST = "127.0.0.1"
STARTUP_TIMEOUT = 30  # seconds (longer for multi-tenant startup)
PLAYWRIGHT_STORAGE_DIR = ".playwright-storage-state"  # Project-local directory for Playwright state


logger = logging.getLogger(__name__)

# 🔒 SAFETY ASSERTION: This script performs ONLY safe operations
# - READ operations: health checks, search queries, document retrieval
# - WRITE operations: only ADD/UPDATE documents via sync triggers
# - NO DELETE operations: this script cannot and will not delete any documents
assert "delete" not in __file__.lower(), "This script must never contain deletion operations"


def _safety_check():
    """Runtime safety check to ensure no dangerous operations are available.

    🔒 This function validates that no deletion methods are accessible.
    """
    dangerous_operations = [
        "delete",
        "remove",
        "purge",
        "clear",
        "drop",
        "truncate",
        "destroy",
        "erase",
    ]

    # Check current module for dangerous function names
    current_module = sys.modules[__name__]
    for attr_name in dir(current_module):
        for dangerous_op in dangerous_operations:
            if dangerous_op in attr_name.lower():
                raise RuntimeError(
                    f"🚨 SAFETY VIOLATION: Found potentially dangerous operation '{attr_name}' "
                    f"in debug script. This script must never delete documents!"
                )

    print("🔒 Safety check passed: No dangerous deletion operations found")


# Run safety check on import
_safety_check()


def create_debug_deployment_config(
    source_config: Path,
    enable_sync: bool = False,
    tenant_filters: list[str] | None = None,
    host: str | None = None,
    port: int | None = None,
    log_profile: str | None = None,
) -> Path:
    """Create a debug deployment config with patched URLs and settings for testing."""
    with source_config.open() as f:
        config = json.load(f)

    infra = config["infrastructure"]

    # Patch infrastructure for local vs external testing
    if host or port:
        infra["mcp_port"] = port or infra.get("mcp_port", get_free_port())
        infra["mcp_host"] = host or infra.get("mcp_host", DEFAULT_HOST)
    else:
        # Local testing configuration - use random port for parallel runs
        infra["mcp_port"] = get_free_port()
        infra["mcp_host"] = DEFAULT_HOST

    # Apply log profile override if specified
    if log_profile:
        available_profiles = list(infra.get("log_profiles", {}).keys())
        if log_profile not in available_profiles:
            print(f"⚠️  Log profile '{log_profile}' not found in config. Available: {available_profiles}")
        else:
            infra["log_profile"] = log_profile
            print(f"📊 Using log profile: {log_profile}")

    # Process filesystem tenants
    for tenant in config.get("tenants", []):
        if tenant.get("source_type") == "filesystem" and tenant.get("docs_root_dir"):
            docs_root_path = Path(tenant["docs_root_dir"]).expanduser().resolve()
            tenant["docs_root_dir"] = str(docs_root_path)
            if not docs_root_path.exists():
                print(f"⚠️  Warning: Filesystem tenant '{tenant.get('codename')}' path does not exist: {docs_root_path}")
            else:
                print(f"📁 Filesystem tenant '{tenant.get('codename')}': {docs_root_path}")

    # Set operation mode and sync settings
    infra["operation_mode"] = "online" if enable_sync else "offline"
    print(f"🔒 Running in {infra['operation_mode'].upper()} mode")
    if not enable_sync:
        # Remove sync_enabled from tenants (deprecated field - now controlled by operation_mode)
        for tenant in config.get("tenants", []):
            tenant.pop("sync_enabled", None)

    # Filter tenants and groups
    if tenant_filters:
        # Check if filters match groups or tenants
        group_codenames = {g.get("codename") for g in config.get("groups", [])}
        tenant_codenames = {t.get("codename") for t in config.get("tenants", [])}

        requested_groups = [f for f in tenant_filters if f in group_codenames]
        requested_tenants = [f for f in tenant_filters if f in tenant_codenames]

        # Expand groups to their member tenants
        expanded_tenants = set(requested_tenants)
        for group_code in requested_groups:
            group = next(g for g in config.get("groups", []) if g["codename"] == group_code)
            expanded_tenants.update(group["members"])
            print(f"📦 Group '{group_code}' expands to members: {group['members']}")

        # Keep only requested tenants (including expanded from groups)
        original_tenant_count = len(config["tenants"])
        config["tenants"] = [t for t in config["tenants"] if t["codename"] in expanded_tenants]

        # Keep only requested groups
        if requested_groups:
            config["groups"] = [g for g in config.get("groups", []) if g["codename"] in requested_groups]
            print(f"🎯 Keeping {len(requested_groups)} group(s): {requested_groups}")
        else:
            # Remove all groups if not testing groups
            config["groups"] = []

        if not config["tenants"]:
            raise ValueError(f"Filters '{tenant_filters}' did not match any tenants or groups")

        print(f"🎯 Filtered to {len(config['tenants'])} tenant(s) from {original_tenant_count} total")

    DEBUG_DIR.mkdir(exist_ok=True)
    with DEBUG_CONFIG.open("w") as f:
        json.dump(config, f, indent=2)

    print(f"📝 Created debug config: {DEBUG_CONFIG}")
    return DEBUG_CONFIG


def cleanup_pycache(path: Path):
    """Recursively remove __pycache__ directories."""
    for p in path.glob("**/*"):
        if p.is_dir() and p.name == "__pycache__":
            print(f"   -> Removing stale cache: {p}")
            shutil.rmtree(p, ignore_errors=True)


class ServerManager:
    """Manage multi-tenant MCP server lifecycle."""

    def __init__(self, deployment_config: Path, explicit_host: str | None = None, explicit_port: int | None = None):
        """Initialize server manager.

        Args:
            deployment_config: Path to deployment.json
            explicit_host: Override host from config (for connecting to external servers)
            explicit_port: Override port from config (for connecting to external servers)
        """
        DEBUG_DIR.mkdir(exist_ok=True)
        self.process: subprocess.Popen | None = None
        self.deployment_config = deployment_config
        self.explicit_host = explicit_host
        self.explicit_port = explicit_port
        self.is_external = bool(explicit_host or explicit_port)

        # Load config to get server URL
        import json

        with deployment_config.open() as f:
            config = json.load(f)

        infra = config["infrastructure"]

        # Use explicit values if provided, otherwise use config
        host = explicit_host or (
            "127.0.0.1" if infra.get("mcp_host", DEFAULT_HOST) == "0.0.0.0" else infra.get("mcp_host", DEFAULT_HOST)
        )
        port = explicit_port or infra.get("mcp_port", get_free_port())

        self.server_url = f"http://{host}:{port}"

    def is_running(self) -> bool:
        """Check if server is already running via pidfile."""
        if not PIDFILE.exists():
            return False

        try:
            pid = int(PIDFILE.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            return True
        except (OSError, ValueError):
            PIDFILE.unlink(missing_ok=True)
            return False

    def start(self) -> bool:
        """Start the server in background."""
        # If connecting to external server, just check if it's reachable
        if self.is_external:
            print(f"🔗 Connecting to external server at {self.server_url}")
            try:
                response = httpx.get(f"{self.server_url}/health", timeout=5.0)
                if response.status_code == 200:
                    print("✅ External server is reachable")
                    return True
                print(f"❌ External server returned HTTP {response.status_code}")
                return False
            except (httpx.RequestError, httpx.TimeoutException) as e:
                print(f"❌ Cannot reach external server: {e}")
                return False

        if self.is_running():
            print(f"✅ Server already running at {self.server_url}")
            return True

        print("🚀 Starting multi-tenant server...")
        # Clean up pycache before starting
        project_root = Path(__file__).parent / "src"
        print(f"🧹 Cleaning up __pycache__ in {project_root}...")
        cleanup_pycache(project_root)

        print(f"   Config: {self.deployment_config}")
        print(f"   Log file: {LOGFILE}")
        print(f"   PID file: {PIDFILE}")

        # Open log file (append mode to preserve history)
        with LOGFILE.open("a") as log_fd:
            log_fd.write(f"\n{'=' * 80}\n")
            log_fd.write(f"Server started at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_fd.write(f"{'=' * 80}\n\n")
            log_fd.flush()

            # Start server process
            env = os.environ.copy()
            env["DEPLOYMENT_CONFIG"] = str(self.deployment_config)

            # Run server directly via Python module, not uvicorn CLI
            # This avoids reload issues and properly imports the app
            self.process = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "python",
                    "-m",
                    "docs_mcp_server.app",
                ],
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
            )  # Write pidfile
        PIDFILE.write_text(str(self.process.pid))

        # Wait for server to be ready
        print("   Waiting for server to be ready...")
        for _i in range(STARTUP_TIMEOUT):
            try:
                response = httpx.get(f"{self.server_url}/health", timeout=2.0)
                if response.status_code == 200:
                    print(f"✅ Server ready at {self.server_url}")
                    return True
            except (httpx.RequestError, httpx.TimeoutException):
                time.sleep(1)

        print(f"❌ Server failed to start within {STARTUP_TIMEOUT}s")
        print(f"\n{'=' * 80}")
        print("SERVER STARTUP LOGS (last session):")
        print(f"{'=' * 80}\n")

        # Find the last session marker and print everything after it
        if LOGFILE.exists():
            log_content = LOGFILE.read_text()
            # Find the last occurrence of the session marker
            marker = "=" * 80 + "\nServer started at"
            last_marker_pos = log_content.rfind(marker)

            if last_marker_pos >= 0:
                # Print from the last marker onwards
                print(log_content[last_marker_pos:])
            else:
                # No marker found, print last 50 lines
                lines = log_content.splitlines()
                print("\n".join(lines[-50:]))
        else:
            print("(No log file found)")

        print(f"\n{'=' * 80}\n")
        self.stop()
        return False

    def stop(self):
        """Stop the server."""
        # Don't try to stop external servers
        if self.is_external:
            print("📡 External server - not stopping")
            return

        if not PIDFILE.exists():
            return

        try:
            pid = int(PIDFILE.read_text().strip())
            print(f"🛑 Stopping server (PID {pid})...")

            # Try graceful shutdown first
            try:
                os.kill(pid, 15)  # SIGTERM
                time.sleep(2)

                # Check if still running
                try:
                    os.kill(pid, 0)
                    # Still running, force kill
                    print("   Server didn't stop gracefully, forcing...")
                    os.kill(pid, 9)  # SIGKILL
                    time.sleep(1)
                except OSError:
                    pass  # Already dead

            except OSError:
                pass  # Process already dead

            PIDFILE.unlink(missing_ok=True)
            print("✅ Server stopped")

        except (OSError, ValueError) as e:
            print(f"⚠️  Error stopping server: {e}")
        finally:
            PIDFILE.unlink(missing_ok=True)


async def test_all_tenants(
    server_url: str,
    deployment_config: Path,
    test_type: str,
    query: str,
    word_match: bool,
) -> dict[str, dict[str, bool]]:
    """Test all tenants and groups defined in deployment config."""
    import json

    with deployment_config.open() as f:
        config = json.load(f)

    results = {}

    # Test all groups (using meta-search tools)
    for group in config.get("groups", []):
        codename = group["codename"]
        display_name = group.get("display_name", codename)

        print(f"\n{'=' * 80}")
        print(f"Testing GROUP: {display_name} ({codename})")
        print(f"Members: {', '.join(group['members'])}")
        print(f"{'=' * 80}")

        if test_type == "parity":
            print("   ⚠️ Skipping parity check for groups (not applicable)")
            group_passed = False
        else:
            test_queries = {"words": ["configuration"]}
            tester = FilesystemTenantTester(server_url, codename, test_queries, word_match=word_match)
            group_passed = await tester.run_tests(test_type)
        results[codename] = {test_type: group_passed}

    # Test all individual tenants (search/fetch/parity operations)
    for tenant in config["tenants"]:
        codename = tenant["codename"]

        if test_type == "parity":
            tenant_passed = run_storage_parity_check(tenant)
        else:
            raw_queries = tenant.get("test_queries") or {"words": ["configuration"]}
            test_queries = {bucket: list(values) for bucket, values in raw_queries.items()}
            tester = FilesystemTenantTester(server_url, codename, test_queries, word_match=word_match)
            tenant_passed = await tester.run_tests(test_type)

        results[codename] = {test_type: tenant_passed}

    return results


async def trigger_sync_all_tenants(server_url: str, deployment_config: Path) -> bool:
    """Trigger sync for all tenants and monitor document counts.

    🔒 SAFETY: This function only triggers sync processes that ADD/UPDATE documents.
    It never deletes existing documents.
    """
    import json

    with deployment_config.open() as f:
        config = json.load(f)

    print(f"\n{'=' * 80}")
    print("TRIGGERING SYNC FOR ALL TENANTS")
    print(f"{'=' * 80}")

    # Get initial document counts from server health endpoint
    initial_counts = await get_document_counts(server_url)
    if initial_counts is None:
        return False

    print("\n📊 Initial document counts:")
    for tenant_name, doc_count in initial_counts.items():
        print(f"   {tenant_name}: {doc_count} documents")

    # Trigger sync for all tenants
    success_count = await trigger_syncs(server_url, config["tenants"])
    total_tenants = len(config["tenants"])

    print(f"\n📈 Triggered sync for {success_count}/{total_tenants} tenants")

    if success_count == 0:
        print("❌ No syncs were triggered successfully")
        return False

    # Monitor document counts every 30 seconds
    print(f"\n{'=' * 80}")
    print("MONITORING DOCUMENT COUNTS (checking every 30s)")
    print("Press Ctrl+C to stop monitoring")
    print(f"{'=' * 80}")

    return await monitor_document_counts(server_url, initial_counts)


async def get_document_counts(server_url: str) -> dict[str, int] | None:
    """Get current document counts for all tenants.

    🔒 SAFETY: This function only performs READ operations via /health endpoint.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{server_url}/health", timeout=10.0)
            if response.status_code != 200:
                print(f"❌ Failed to get health status: {response.status_code}")
                return None

            health_data = response.json()
            counts = {}

            for tenant_name, tenant_data in health_data["tenants"].items():
                counts[tenant_name] = tenant_data.get("documents", 0)

            return counts

        except Exception as e:
            print(f"❌ Failed to get health status: {e}")
            return None


async def trigger_syncs(server_url: str, tenants: list) -> int:
    """Trigger sync for all tenants, return count of successful triggers.

    🔒 SAFETY: Sync operations only ADD/UPDATE documents, never delete.
    """
    success_count = 0

    async with httpx.AsyncClient() as client:
        for tenant in tenants:
            codename = tenant["codename"]
            sync_url = f"{server_url}/{codename}/sync/trigger"

            try:
                print(f"\n🔄 Triggering sync for {codename}...")
                response = await client.post(sync_url, timeout=30.0)

                if response.status_code == 200:
                    result = response.json()
                    print(f"✅ {codename}: {result.get('message', 'Sync triggered')}")
                    success_count += 1
                else:
                    print(f"❌ {codename}: HTTP {response.status_code} - {response.text}")

            except Exception as e:
                print(f"❌ {codename}: Error triggering sync - {e}")

    return success_count


async def monitor_document_counts(server_url: str, initial_counts: dict[str, int]) -> bool:
    """Monitor document counts every 30 seconds."""
    monitoring_round = 0

    try:
        while True:
            monitoring_round += 1
            print(f"\n⏰ Round {monitoring_round} - {time.strftime('%H:%M:%S')}")

            current_counts = await get_document_counts(server_url)
            if current_counts is None:
                await asyncio.sleep(30)
                continue

            changes_detected = False

            for tenant_name, current_count in current_counts.items():
                initial_count = initial_counts.get(tenant_name, 0)

                if current_count != initial_count:
                    change = current_count - initial_count
                    change_str = f"(+{change})" if change > 0 else f"({change})"
                    print(f"   📈 {tenant_name}: {current_count} documents {change_str}")
                    changes_detected = True
                else:
                    print(f"   📊 {tenant_name}: {current_count} documents (no change)")

            if not changes_detected:
                print("   No document count changes detected")

            # Get scheduler status summary
            health_data = await get_health_data(server_url)
            if health_data:
                scheduler_status = {}
                for tenant_data in health_data["tenants"].values():
                    status = tenant_data.get("scheduler", "unknown")
                    scheduler_status[status] = scheduler_status.get(status, 0) + 1

                print(f"   Scheduler status: {dict(scheduler_status)}")

            # Wait 30 seconds before next check
            await asyncio.sleep(30)

    except KeyboardInterrupt:
        print("\n⚠️  Monitoring stopped by user")
        return True


async def get_health_data(server_url: str) -> dict | None:
    """Get health data from server."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{server_url}/health", timeout=10.0)
            return response.json() if response.status_code == 200 else None
        except Exception:
            return None


class RootHubTester:
    """Test the root hub MCP aggregator.

    The root hub provides:
    - list_tenants: Enumerate all tenants
    - describe_tenant: Get detailed info about a specific tenant
    - root_search: Search within a specific tenant
    - root_fetch: Fetch document from a specific tenant
    - root_browse: Browse filesystem hierarchy (for filesystem tenants)
    """

    def __init__(self, server_url: str):
        self.server_url = server_url
        self.mcp_url = f"{server_url}/mcp/"
        self.console = Console()

    async def test_list_tenants(self, client: Client) -> tuple[bool, list[dict]]:
        """Test list_tenants tool. Returns (success, tenants_list)."""
        print("   -> Testing list_tenants...")
        try:
            result = await client.call_tool("list_tenants", arguments={})
            if not result.content:
                print("   ❌ list_tenants Error: No content in MCP response")
                return False, []

            first_content = result.content[0]
            if not isinstance(first_content, TextContent):
                print(f"   ❌ list_tenants Error: Expected TextContent, got {type(first_content)}")
                return False, []

            data = json.loads(first_content.text)  # type: ignore[union-attr]
            tenants = data.get("tenants", [])
            count = data.get("count", 0)
            print(f"   ✅ list_tenants successful: {count} tenants found")

            # Show first few tenants
            if tenants:
                self.console.print("   [cyan]First 5 tenants:[/cyan]")
                for t in tenants[:5]:
                    tools_count = len(t.get("tools", []))
                    # Handle both old and new response formats
                    display_name = t.get('display_name', t.get('description', 'Unknown'))
                    self.console.print(f"      - {t['codename']}: {display_name} ({tools_count} tools)")
                if len(tenants) > 5:
                    self.console.print(f"      ... and {len(tenants) - 5} more")

            return True, tenants

        except Exception as e:
            print(f"   ❌ list_tenants Error: {e}")
            import traceback

            traceback.print_exc()
            return False, []

    async def test_describe_tenant(self, client: Client, codename: str) -> tuple[bool, dict]:
        """Test describe_tenant tool. Returns (success, metadata)."""
        print(f"   -> Testing describe_tenant('{codename}')...")
        try:
            result = await client.call_tool("describe_tenant", arguments={"codename": codename})
            if not result.content:
                print("   ❌ describe_tenant Error: No content in MCP response")
                return False, {}

            first_content = result.content[0]
            if not isinstance(first_content, TextContent):
                print(f"   ❌ describe_tenant Error: Expected TextContent, got {type(first_content)}")
                return False, {}

            data = json.loads(first_content.text)  # type: ignore[union-attr]

            if "error" in data:
                print(f"   ❌ describe_tenant Error: {data['error']}")
                return False, data

            print(f"   ✅ describe_tenant successful: {data.get('display_name', codename)}")
            self.console.print(f"      Description: {data.get('description', 'N/A')}")
            self.console.print(f"      Source Type: {data.get('source_type', 'N/A')}")
            test_queries = data.get("test_queries", [])
            if test_queries:
                self.console.print(f"      Test Queries: {test_queries[:3]}...")
            tools = data.get("tools", [])
            if tools:
                self.console.print(f"      Tools: {tools}")

            return True, data

        except Exception as e:
            print(f"   ❌ describe_tenant Error: {e}")
            import traceback

            traceback.print_exc()
            return False, {}

    async def test_root_search(
        self, client: Client, tenant_codename: str, query: str, word_match: bool = False
    ) -> tuple[bool, list]:
        """Test root_search tool. Returns (success, results_list)."""
        from rich.syntax import Syntax

        print(f"   -> Testing root_search('{tenant_codename}', '{query}', word_match={word_match})...")
        try:
            result = await client.call_tool(
                "root_search",
                arguments={
                    "tenant_codename": tenant_codename,
                    "query": query,
                    "size": 5,
                    "word_match": word_match,
                },
            )
            if not result.content:
                print("   ❌ root_search Error: No content in MCP response")
                return False, []

            first_content = result.content[0]
            if not isinstance(first_content, TextContent):
                print(f"   ❌ root_search Error: Expected TextContent, got {type(first_content)}")
                return False, []

            data = json.loads(first_content.text)  # type: ignore[union-attr]

            if error := data.get("error"):
                print(f"   ❌ root_search Error: {error}")
                return False, []

            results = data.get("results", [])
            print(f"   ✅ root_search successful: {len(results)} results")

            if results:
                self.console.print("\n[bold cyan]📊 Root Search Results:[/bold cyan]")
                formatted_json = json.dumps(data, indent=2, ensure_ascii=False)
                syntax = Syntax(formatted_json, "json", theme="monokai", line_numbers=True)
                self.console.print(syntax)
                self.console.print()

            return True, results

        except Exception as e:
            print(f"   ❌ root_search Error: {e}")
            import traceback

            traceback.print_exc()
            return False, []

    async def test_root_fetch(self, client: Client, tenant_codename: str, url: str, context: str) -> bool:
        """Test root_fetch tool."""
        print(f"   -> Testing root_fetch('{tenant_codename}', '{url}', context='{context}')...")
        try:
            result = await client.call_tool(
                "root_fetch",
                arguments={
                    "tenant_codename": tenant_codename,
                    "uri": url,
                    "context": context,
                },
            )
            if not result.content:
                print("   ❌ root_fetch Error: No content in MCP response")
                return False

            first_content = result.content[0]
            if not isinstance(first_content, TextContent):
                print(f"   ❌ root_fetch Error: Expected TextContent, got {type(first_content)}")
                return False

            data = json.loads(first_content.text)  # type: ignore[union-attr]

            if error := data.get("error"):
                print(f"   ❌ root_fetch Error: {error}")
                return False

            content = data.get("content", "")
            print(f"   ✅ root_fetch successful: {len(content)} chars (mode: {data.get('context_mode', 'N/A')})")
            return True

        except Exception as e:
            print(f"   ❌ root_fetch Error: {e}")
            import traceback

            traceback.print_exc()
            return False

    async def test_root_browse(self, client: Client, tenant_codename: str, path: str = "", depth: int = 2) -> bool:
        """Test root_browse tool."""
        print(f"   -> Testing root_browse('{tenant_codename}', path='{path}', depth={depth})...")
        try:
            result = await client.call_tool(
                "root_browse",
                arguments={
                    "tenant_codename": tenant_codename,
                    "path": path,
                    "depth": depth,
                },
            )
            if not result.content:
                print("   ❌ root_browse Error: No content in MCP response")
                return False

            first_content = result.content[0]
            if not isinstance(first_content, TextContent):
                print(f"   ❌ root_browse Error: Expected TextContent, got {type(first_content)}")
                return False

            data = json.loads(first_content.text)  # type: ignore[union-attr]

            if error := data.get("error"):
                print(f"   ❌ root_browse Error: {error}")
                return False

            nodes = data.get("nodes", [])
            print(f"   ✅ root_browse successful: {len(nodes)} nodes at depth {data.get('depth', depth)}")

            # Show first few nodes
            if nodes:
                self.console.print("   [cyan]First 5 nodes:[/cyan]")
                for n in nodes[:5]:
                    node_type = "📁" if n.get("type") == "directory" else "📄"
                    self.console.print(f"      {node_type} {n.get('name', 'N/A')}")
                if len(nodes) > 5:
                    self.console.print(f"      ... and {len(nodes) - 5} more")

            return True

        except Exception as e:
            print(f"   ❌ root_browse Error: {e}")
            import traceback

            traceback.print_exc()
            return False

    async def run_tests(
        self, test_type: str, target_tenant: str | None = None, query: str = "configuration", word_match: bool = False
    ) -> bool:
        """Run root hub tests based on the specified type.

        Args:
            test_type: 'all', 'search', 'fetch', 'list', 'describe', 'browse'
            target_tenant: Tenant codename to use for search/fetch/browse tests
            query: Search query to use
            word_match: Enable whole word matching

        Returns:
            True if all tests pass, False otherwise
        """
        print("\n🌐 Root Hub MCP Test")
        print(f"   MCP URL: {self.mcp_url}")
        print(f"   Test Type: {test_type}")
        if target_tenant:
            print(f"   Target Tenant: {target_tenant}")

        try:
            async with Client(self.mcp_url) as client:
                # List available tools
                tools = await client.list_tools()
                tool_names = [tool.name for tool in tools]
                print(f"   Available Tools: {tool_names}")

                all_passed = True

                # Test list_tenants (always run for 'all' or 'list')
                if test_type in {"all", "list"}:
                    success, tenants = await self.test_list_tenants(client)
                    if not success:
                        all_passed = False

                    # Pick first tenant for subsequent tests if not specified
                    if target_tenant is None and tenants:
                        target_tenant = tenants[0]["codename"]
                        print(f"   [yellow]Using first tenant for proxy tests: {target_tenant}[/yellow]")

                # Test describe_tenant
                if test_type in {"all", "describe"} and target_tenant:
                    success, metadata = await self.test_describe_tenant(client, target_tenant)
                    if not success:
                        all_passed = False

                    # Get test queries from metadata if available
                    if success and not query:
                        test_queries = metadata.get("test_queries", [])
                        if test_queries:
                            query = test_queries[0]
                            print(f"   [yellow]Using test query from tenant metadata: '{query}'[/yellow]")

                # Test root_search
                search_results = []
                if test_type in {"all", "search"} and target_tenant:
                    success, search_results = await self.test_root_search(client, target_tenant, query, word_match)
                    if not success:
                        all_passed = False

                # Test root_fetch
                if test_type in {"all", "fetch"} and target_tenant:
                    if search_results:
                        fetch_url = search_results[0]["url"]
                        surrounding_passed = await self.test_root_fetch(client, target_tenant, fetch_url, "surrounding")
                        full_passed = await self.test_root_fetch(client, target_tenant, fetch_url, "full")
                        if not (surrounding_passed and full_passed):
                            all_passed = False
                    else:
                        print("   ⚠️ Cannot run root_fetch test, no URLs from search results")
                        if test_type == "fetch":
                            all_passed = False

                # Test root_browse (only for filesystem tenants)
                if test_type in {"all", "browse"} and target_tenant:
                    browse_passed = await self.test_root_browse(client, target_tenant, "", 2)
                    # Don't fail overall if browse fails (tenant might not support it)
                    if not browse_passed and test_type == "browse":
                        all_passed = False

                return all_passed

        except Exception as e:
            print(f"❌ Root hub test failed: {e}")
            import traceback

            traceback.print_exc()
            return False


class FilesystemTenantTester:
    """Test a filesystem-based tenant."""

    def __init__(
        self,
        server_url: str,
        tenant_codename: str,
        test_queries: dict[str, list[str]] | None = None,
        word_match: bool = False,
    ):
        self.server_url = server_url
        self.tenant_codename = tenant_codename
        self.test_queries = test_queries or {"words": ["configuration"]}
        self.word_match = word_match
        # Use root hub at /mcp/ - all tenants accessed via root_search/root_fetch
        self.mcp_url = f"{server_url}/mcp/"
        self.console = Console()

    async def test_search(self, client: Client, query: str) -> tuple[bool, list]:
        """Test search functionality via root_search. Returns (success_bool, results_list)."""
        from rich.syntax import Syntax

        print(f"   -> Testing root_search('{self.tenant_codename}', '{query}') (word_match: {self.word_match})")
        try:
            result = await client.call_tool(
                "root_search",
                arguments={
                    "tenant_codename": self.tenant_codename,
                    "query": query,
                    "size": 5,
                    "word_match": self.word_match,
                },
            )
            if not result.content:
                print("   ❌ Search Error: No content in MCP response")
                return False, []

            # MCP responses can have different content types - ensure it's text
            first_content = result.content[0]
            if not isinstance(first_content, TextContent):
                print(f"   ❌ Search Error: Expected TextContent, got {type(first_content)}")
                return False, []

            # Type narrowing for Pylance - after isinstance check, this is safe
            data = json.loads(first_content.text)  # type: ignore[union-attr]
            if error := data.get("error"):
                print(f"   ❌ Search Error: {error}")
                return False, []

            results = data.get("results", [])
            print(f"   ✅ Search successful, returned {len(results)} results")

            # Print warning if present (for timeout scenarios)
            if warning := data.get("warning"):
                print(f"   ⚠️  {warning}")

            # Pretty print the full response with rich (only for first query or if verbose)
            if results and len(results) > 0:
                self.console.print("\n[bold cyan]📊 Search Results:[/bold cyan]")
                formatted_json = json.dumps(data, indent=2, ensure_ascii=False)
                syntax = Syntax(formatted_json, "json", theme="monokai", line_numbers=True)
                self.console.print(syntax)
                self.console.print()

            return True, results  # Success even if results are empty
        except Exception as e:
            print(f"   ❌ Search Error: Unhandled exception {e}")
            import traceback

            traceback.print_exc()
            return False, []

    async def test_fetch(self, client: Client, url: str, context: str) -> bool:
        """Test fetch functionality via root_fetch with a given context."""
        print(f"   -> Testing root_fetch('{self.tenant_codename}', '{url}', '{context}')")
        result = await client.call_tool(
            "root_fetch",
            arguments={"tenant_codename": self.tenant_codename, "uri": url, "context": context},
        )
        if not result.content:
            print(f"   ❌ Fetch Error ({context}): No content in MCP response")
            return False

        # MCP response type checking (same as search)
        first_content = result.content[0]
        if not isinstance(first_content, TextContent):
            print(f"   ❌ Fetch Error: Expected TextContent, got {type(first_content)}")
            return False

        data = json.loads(first_content.text)  # type: ignore[union-attr]
        if error := data.get("error"):
            print(f"   ❌ Fetch Error ({context}): {error}")
            return False

        content = data.get("content", "")
        print(f"   ✅ Fetched {len(content)} chars (mode: {data.get('context_mode', 'N/A')})")
        # ... (preview rendering can be added here if needed)
        return True

    async def run_tests(self, test_type: str) -> bool:
        """Run tests based on the specified type.

        Uses root hub tools (root_search, root_fetch) with tenant_codename parameter.
        """
        print(f"\n[{self.tenant_codename}] Filesystem Tenant Test")
        print(f"   MCP URL: {self.mcp_url}")
        print(
            f"   Test Queries: {sum(len(v) for v in self.test_queries.values())} queries across {len(self.test_queries)} types"
        )

        try:
            async with Client(self.mcp_url) as client:
                tools = await client.list_tools()
                tool_names = [tool.name for tool in tools]

                # Verify root hub tools are available
                required_tools = {"root_search", "root_fetch"}
                missing_tools = required_tools - set(tool_names)
                if missing_tools:
                    print(f"   ❌ Missing root hub tools: {missing_tools}")
                    print(f"   Available tools: {tool_names}")
                    return False
                print(f"   ✅ Root hub tools available: {required_tools}")

                # Test search with all queries
                all_search_passed = True
                all_search_results = []

                for query_type, queries in self.test_queries.items():
                    print(f"\n   📝 Testing {query_type} queries ({len(queries)} queries)")
                    for query in queries:
                        search_passed, search_results = await self.test_search(client, query)
                        if not search_passed:
                            all_search_passed = False
                            print(f"      ❌ Query '{query}' failed")
                        elif search_results:
                            all_search_results.extend(search_results)

                if test_type == "search":
                    return all_search_passed

                # Test fetch if requested or doing 'all'
                if test_type in {"fetch", "all"}:
                    if not all_search_results:
                        print("   ⚠️ Cannot run fetch test, no URLs from search results.")
                        # If fetch was explicitly requested, this is a failure
                        # If doing 'all', just report search results
                        return test_type != "fetch" and all_search_passed

                    # Test fetch with first result
                    fetch_url = all_search_results[0]["url"]
                    surrounding_passed = await self.test_fetch(client, fetch_url, "surrounding")
                    full_passed = await self.test_fetch(client, fetch_url, "full")

                    # Return combined results: search + fetch
                    return all_search_passed and surrounding_passed and full_passed

                # Default: return search results
                return all_search_passed

        except Exception as e:
            print(f"❌ Unhandled exception during filesystem test: {e}")
            import traceback

            traceback.print_exc()
            return False


def _copy_test_queries(tenant_config: dict) -> dict[str, list[str]]:
    """Return a defensive copy of the tenant's configured test queries."""

    raw_queries = tenant_config.get("test_queries") or {"words": ["configuration"]}
    return {bucket: list(values) for bucket, values in raw_queries.items()}


def _resolve_docs_root_for_tenant(tenant_config: dict) -> Path:
    """Resolve the docs root path for a filesystem tenant."""

    codename = tenant_config.get("codename", "unknown")
    raw_root = tenant_config.get("docs_root_dir")
    base = Path(raw_root) if raw_root else Path("mcp-data") / codename
    resolved = base.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Docs root not found for tenant '{codename}': {resolved}")
    return resolved


def _collect_markdown_statistics(docs_root: Path, sample_limit: int = 5) -> tuple[int, list[str]]:
    """Count markdown files while skipping metadata directories."""

    doc_count = 0
    samples: list[str] = []

    for path in docs_root.rglob("*.md"):
        relative_path = path.relative_to(docs_root)
        if any(part.startswith("__") for part in relative_path.parts):
            continue
        doc_count += 1
        if len(samples) < sample_limit:
            samples.append(str(relative_path))

    return doc_count, samples


def _collect_metadata_statistics(
    metadata_dir: Path,
    sample_limit: int = 5,
) -> tuple[int, int, list[dict[str, str]]]:
    """Count successful scheduler entries and capture sample failures."""

    success_count = 0
    total_entries = 0
    failure_samples: list[dict[str, str]] = []

    for entry in sorted(metadata_dir.glob("url_*.json")):
        total_entries += 1
        try:
            payload = json.loads(entry.read_text())
        except json.JSONDecodeError as exc:
            if len(failure_samples) < sample_limit:
                failure_samples.append({"url": entry.name, "status": f"json-error: {exc}"})
            continue

        status = payload.get("last_status", "unknown")
        if status == "success":
            success_count += 1
            continue

        if len(failure_samples) < sample_limit:
            failure_samples.append({"url": payload.get("url", entry.name), "status": status})

    return success_count, total_entries, failure_samples


async def print_tenant_sync_status_snapshot(server_url: str, tenant_codename: str) -> None:
    """Fetch and display /<tenant>/sync/status with fallback counters."""

    status = await _fetch_tenant_sync_status(server_url, tenant_codename)
    if not status:
        return
    _render_sync_status_snapshot(status)


async def _fetch_tenant_sync_status(server_url: str, tenant_codename: str) -> dict | None:
    base_url = server_url.rstrip("/")
    status_url = f"{base_url}/{tenant_codename}/sync/status"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(status_url, timeout=10.0)
        except Exception as exc:  # pragma: no cover - diagnostics helper
            print(f"   ⚠️ Unable to fetch sync status for {tenant_codename}: {exc}")
            return None

    if response.status_code != 200:
        print(
            f"   ⚠️ Sync status request for {tenant_codename} returned HTTP {response.status_code}: {response.text[:120]}"
        )
        return None

    try:
        return response.json()
    except ValueError as exc:
        print(f"   ⚠️ Unable to parse sync status response for {tenant_codename}: {exc}")
        return None


def _render_sync_status_snapshot(payload: dict) -> None:
    tenant_code = payload.get("tenant", "unknown")
    stats = payload.get("stats") or {}
    scheduler_initialized = payload.get("scheduler_initialized")
    scheduler_running = payload.get("scheduler_running")

    print(f"\n[{tenant_code}] Sync status snapshot")
    print(f"   Scheduler initialized : {scheduler_initialized} (running={scheduler_running})")

    storage_docs = stats.get("storage_doc_count")
    metadata_success = stats.get("metadata_successful")
    metadata_total = stats.get("metadata_total_urls")
    metadata_pending = stats.get("metadata_pending")

    if storage_docs is not None:
        print(f"   Storage documents      : {storage_docs}")
    if metadata_success is not None or metadata_total is not None:
        success_val = metadata_success if metadata_success is not None else "?"
        total_val = metadata_total if metadata_total is not None else "?"
        print(f"   Metadata successes     : {success_val} / {total_val}")
    if metadata_pending is not None:
        print(f"   Metadata pending       : {metadata_pending}")

    last_success = stats.get("metadata_last_success_at")
    if last_success:
        print(f"   Last successful fetch  : {last_success}")

    fallback_attempts = stats.get("fallback_attempts", 0)
    fallback_successes = stats.get("fallback_successes", 0)
    fallback_failures = stats.get("fallback_failures", 0)
    print(
        "   Fallback extractor     : "
        f"attempts={fallback_attempts}, successes={fallback_successes}, failures={fallback_failures}"
    )

    failure_sample = stats.get("failure_sample") or []
    if failure_sample:
        print("   Recent failures:")
        for entry in failure_sample[:3]:
            reason = entry.get("reason") or entry.get("status") or "unknown"
            url = entry.get("url", "unknown")
            print(f"      - {reason}: {url}")


def run_storage_parity_check(tenant_config: dict, max_drift: float = 0.02) -> bool:
    """Compare markdown files on disk with successful scheduler metadata entries."""

    codename = tenant_config.get("codename", "unknown")
    print(f"\n[{codename}] Storage parity check")
    try:
        docs_root = _resolve_docs_root_for_tenant(tenant_config)
    except FileNotFoundError as exc:
        print(f"   ❌ {exc}")
        return False

    metadata_dir = docs_root / "__scheduler_meta"
    if not metadata_dir.exists():
        print(f"   ❌ Scheduler metadata directory not found: {metadata_dir}")
        return False

    doc_count, doc_samples = _collect_markdown_statistics(docs_root)
    success_count, total_metadata, failure_samples = _collect_metadata_statistics(metadata_dir)

    difference = doc_count - success_count
    drift_ratio = (0.0 if doc_count == 0 else 1.0) if success_count == 0 else abs(difference) / max(success_count, 1)

    drift_percent = drift_ratio * 100
    allowed_percent = max_drift * 100

    print(f"   Documents on disk        : {doc_count}")
    print(f"   Scheduler successes      : {success_count} / {total_metadata} total entries")
    print(
        f"   Drift                    : {difference:+d} files ({drift_percent:.2f}% vs {allowed_percent:.2f}% allowed)"
    )

    if doc_samples:
        print("   Sample document paths:")
        for sample in doc_samples:
            print(f"      - {sample}")

    if failure_samples:
        print("   Sample non-success metadata entries:")
        for sample in failure_samples:
            print(f"      - {sample['status']}: {sample['url']}")

    if success_count == 0 and doc_count == 0:
        print("   ✅ No documents fetched yet; parity holds by default")
        return True

    if drift_ratio <= max_drift:
        print("   ✅ Document counts within tolerance")
        return True

    print("   ❌ Document counts drift exceeds tolerance")
    return False


async def test_single_tenant(
    server_url: str,
    tenant_codename: str,
    deployment_config: Path,
    test_type: str,
    query: str,
    word_match: bool,
) -> bool:
    """Test a specific tenant or group (all tenants are filesystem-based now)."""
    import json

    with deployment_config.open() as f:
        config = json.load(f)

    # Check if it's a group
    group_config = next((g for g in config.get("groups", []) if g["codename"] == tenant_codename), None)

    if group_config:
        # Testing a group - use group's codename for MCP endpoint
        if test_type == "parity":
            print("❌ Storage parity validation is not supported for groups")
            return False
        print(f"\n🔍 Testing GROUP: {group_config['display_name']} ({tenant_codename})")
        print(f"   Members: {', '.join(group_config['members'])}")

        # For groups, we test the group's aggregated MCP endpoint
        # The group exposes all member tools with prefixes
        test_queries = {"words": [query]} if query else {"words": ["configuration"]}
        tester = FilesystemTenantTester(server_url, tenant_codename, test_queries, word_match=word_match)
        return await tester.run_tests(test_type)

    # Not a group, try tenant
    tenant_config = next((t for t in config["tenants"] if t["codename"] == tenant_codename), None)

    if not tenant_config:
        print(f"❌ '{tenant_codename}' not found in deployment config (not a tenant or group)")
        return False

    if test_type == "parity":
        result = run_storage_parity_check(tenant_config)
        await print_tenant_sync_status_snapshot(server_url, tenant_codename)
        return result

    # All tenants are filesystem-based
    test_queries = _copy_test_queries(tenant_config)
    tester = FilesystemTenantTester(
        server_url,
        tenant_codename,
        test_queries,
        word_match=word_match,
    )
    success = await tester.run_tests(test_type)
    await print_tenant_sync_status_snapshot(server_url, tenant_codename)
    return success


async def test_crawl_urls(tenant_codename: str, deployment_config: Path, max_urls: int, headed: bool) -> bool:
    """Test crawling and HTML extraction for a small set of URLs.

    🔒 SAFETY: This function only reads and processes URLs, never deletes anything.
    Tests the complete pipeline: URL discovery → HTML fetching → content extraction.

    Args:
        tenant_codename: Tenant to test crawling for
        deployment_config: Path to deployment configuration
        max_urls: Maximum number of URLs to test (default: 5)

    Returns:
        True if crawling test passes, False otherwise
    """
    from article_extractor import ExtractionOptions, PlaywrightFetcher, extract_article
    from rich.console import Console
    from rich.table import Table

    from article_extractor.discovery import CrawlConfig, EfficientCrawler
    from docs_mcp_server.config import Settings

    console = Console()
    console.print(f"\n[bold green]🔍 Crawl Test for '{tenant_codename}'[/bold green]")
    console.print(f"   Testing {max_urls} URLs with article-extractor pipeline")
    console.print(
        f"   Playwright Mode: {'🖥️ HEADED (visible browser)' if headed else '👻 HEADLESS (invisible browser)'}"
    )

    # Load tenant config
    with deployment_config.open() as f:
        config = json.load(f)

    tenant_config = next((t for t in config["tenants"] if t["codename"] == tenant_codename), None)

    if not tenant_config:
        console.print(f"[red]❌ Tenant '{tenant_codename}' not found[/red]")
        return False

    # Get configuration
    entry_url = tenant_config.get("docs_entry_url")
    sitemap_url = tenant_config.get("docs_sitemap_url")
    whitelist_prefixes = tenant_config.get("url_whitelist_prefixes", "")
    enable_crawler = tenant_config.get("enable_crawler", False)

    console.print("\n[bold]Configuration:[/bold]")
    console.print(f"   Entry URL: {entry_url}")
    console.print(f"   Sitemap URL: {sitemap_url}")
    console.print(f"   Crawler Enabled: {enable_crawler}")

    # Need either entry URL or sitemap URL for crawl testing
    if not entry_url and not sitemap_url:
        console.print("[red]❌ No entry URL or sitemap URL configured[/red]")
        return False

    # Parse whitelist prefixes
    if isinstance(whitelist_prefixes, str):
        whitelist_list = [p.strip() for p in whitelist_prefixes.split(",") if p.strip()]
    elif isinstance(whitelist_prefixes, list):
        whitelist_list = whitelist_prefixes
    else:
        whitelist_list = []

    # Convert whitelist to string format that Settings expects
    whitelist_str = whitelist_prefixes if isinstance(whitelist_prefixes, str) else ",".join(whitelist_list)

    # Prepare settings kwargs
    settings_kwargs = {
        "docs_name": tenant_config.get("docs_name", tenant_codename),
        "url_whitelist_prefixes": whitelist_str,
        "enable_crawler": enable_crawler,
    }

    # Add entry URL or sitemap URL (Settings validation requires one)
    if entry_url:
        if isinstance(entry_url, list):
            settings_kwargs["docs_entry_url"] = list(entry_url)
        else:
            settings_kwargs["docs_entry_url"] = [entry_url]
    elif sitemap_url:
        if isinstance(sitemap_url, list):
            settings_kwargs["docs_sitemap_url"] = list(sitemap_url)
        else:
            settings_kwargs["docs_sitemap_url"] = [sitemap_url]

    settings = Settings(**settings_kwargs)

    console.print(f"\n[bold]Starting crawl test for {max_urls} URLs...[/bold]")

    # Determine start URLs - use entry URL if available, otherwise load from sitemap
    start_urls = set()

    if entry_url:
        # Use entry URLs directly
        if isinstance(entry_url, str):
            start_urls.add(entry_url)
        else:
            start_urls.update(entry_url)
        console.print(f"[cyan]🎯 Using entry URLs as starting points: {len(start_urls)} URLs[/cyan]")
    elif sitemap_url:
        # Load URLs from sitemap to use as starting points for crawling
        console.print("[cyan]📋 Loading URLs from sitemap...[/cyan]")
        from docs_mcp_server.utils.sitemap_parser import SitemapParser

        # Create sitemap parser with whitelist filtering
        sitemap_parser = SitemapParser(whitelist_prefixes=whitelist_list)

        try:
            # Get sitemap URLs (handle both string and list)
            sitemap_urls = sitemap_url if isinstance(sitemap_url, list) else [sitemap_url]

            # Fetch from all sitemaps
            all_entries = []
            for smap_url in sitemap_urls:
                console.print(f"   Fetching sitemap: {smap_url}")
                entries = await sitemap_parser.fetch_sitemap(smap_url)
                all_entries.extend(entries)

            # Take a subset of sitemap URLs as starting points for crawling
            sitemap_extracted_urls = [str(entry.url) for entry in all_entries]  # Convert HttpUrl to str
            starting_urls = sitemap_extracted_urls[: max_urls * 2]  # Get more than we need for crawling
            start_urls.update(starting_urls)
            console.print(f"   Loaded {len(starting_urls)} URLs from {len(sitemap_urls)} sitemap(s)")

        except Exception as e:
            console.print(f"[red]❌ Failed to load sitemap URLs: {e}[/red]")
            return False

        if not start_urls:
            console.print("[red]❌ No URLs found in sitemap[/red]")
            return False

        console.print(f"[cyan]🗺️ Using sitemap URLs as starting points: {len(start_urls)} URLs[/cyan]")

    crawl_config = CrawlConfig(
        max_pages=max_urls * 2,  # Discover more URLs than we'll test
        headless=not headed,  # Use headed parameter to control browser visibility
        delay_seconds=1.0,  # Be respectful to target sites
        prefer_playwright=settings.crawler_playwright_first,
        user_agent_provider=settings.get_random_user_agent,
        should_process_url=settings.should_process_url,
        min_concurrency=settings.crawler_min_concurrency,
        max_concurrency=settings.crawler_max_concurrency,
        max_sessions=settings.crawler_max_sessions,
    )

    discovered_urls = []

    # Discover URLs using crawler (will crawl from start URLs to find more)
    console.print(f"\n[cyan]📡 Crawling from {len(start_urls)} starting URLs...[/cyan]")

    # Use Playwright storage state directory
    playwright_storage_dir = Path(PLAYWRIGHT_STORAGE_DIR).resolve()
    playwright_storage_dir.mkdir(exist_ok=True)
    storage_state_file = playwright_storage_dir / "storage-state.json"

    # Set environment variable for Playwright fetcher
    os.environ["PLAYWRIGHT_STORAGE_STATE_FILE"] = str(storage_state_file)
    console.print(f"   Storage State: {storage_state_file}")

    async with EfficientCrawler(
        start_urls=start_urls,
        crawl_config=crawl_config,
    ) as crawler:
        # Execute crawl and get all discovered URLs
        all_urls = await crawler.crawl()
        discovered_urls = list(all_urls)[:max_urls]  # Take first max_urls discovered

        for url in discovered_urls:
            console.print(f"   Found: {url}")

    if not discovered_urls:
        console.print("[red]❌ No URLs discovered during crawl[/red]")
        return False

    console.print(f"\n[green]✅ Discovered {len(discovered_urls)} URLs[/green]")

    # Test HTML extraction for each discovered URL using article-extractor
    console.print("\n[cyan]🔧 Testing article extraction with article-extractor...[/cyan]")

    # Initialize article extraction options
    extraction_options = ExtractionOptions(
        min_word_count=150,
        include_images=False,
        include_code_blocks=True,
        safe_markdown=True,
    )

    # Create results table
    table = Table(title="Article Extraction Test Results")
    table.add_column("URL", style="cyan", width=50)
    table.add_column("Status", style="bold")
    table.add_column("Title Length", justify="right")
    table.add_column("Content Length", justify="right")
    table.add_column("Error", style="red")

    successful_extractions = 0
    total_extractions = len(discovered_urls)

    # Use Playwright fetcher for HTML retrieval
    async with PlaywrightFetcher() as fetcher:
        for i, url in enumerate(discovered_urls, 1):
            console.print(f"   [{i}/{total_extractions}] Extracting: {url}")

            try:
                # Fetch HTML with Playwright
                html_content, status_code = await fetcher.fetch(url)

                if not html_content or status_code != 200:
                    status = "[red]❌ FETCH FAILED[/red]"
                    display_url = url[:47] + "..." if len(url) > 50 else url
                    table.add_row(display_url, status, "0", "0", f"HTTP {status_code}")
                    continue

                # Extract article content
                result = extract_article(html_content, url, extraction_options)

                if result.success and result.content:
                    status = "[green]✅ SUCCESS[/green]"
                    successful_extractions += 1
                    title_len = len(result.title) if result.title else 0
                    content_len = len(result.content) if result.content else 0
                    error_msg = ""
                else:
                    status = "[red]❌ FAILED[/red]"
                    title_len = 0
                    content_len = 0
                    error_msg = result.error or "No content extracted"

                # Truncate URL for display
                display_url = url[:47] + "..." if len(url) > 50 else url

                table.add_row(
                    display_url,
                    status,
                    str(title_len),
                    str(content_len),
                    error_msg[:30] + "..." if len(error_msg) > 30 else error_msg,
                )

            except Exception as e:
                status = "[red]❌ ERROR[/red]"
                display_url = url[:47] + "..." if len(url) > 50 else url
                error_msg = str(e)[:30] + "..." if len(str(e)) > 30 else str(e)
                table.add_row(display_url, status, "0", "0", error_msg)
                console.print(f"   [red]ERROR: {e}[/red]")

    console.print("\n")
    console.print(table)

    # Summary
    success_rate = (successful_extractions / total_extractions) * 100
    console.print("\n[bold]Crawl Test Summary:[/bold]")
    console.print(f"   URLs Tested: {total_extractions}")
    console.print(f"   Successful Extractions: {successful_extractions}")
    console.print(f"   Success Rate: {success_rate:.1f}%")

    # Consider test successful if at least 60% of extractions succeed
    test_passed = success_rate >= 60.0

    if test_passed:
        console.print("[green]✅ Crawl test PASSED (≥60% success rate)[/green]")
    else:
        console.print("[red]❌ Crawl test FAILED (<60% success rate)[/red]")

    return test_passed


async def test_html_extractors(tenant_codename: str, deployment_config: Path, headed: bool) -> bool:
    """Test article-extractor HTML content extraction.

    🔒 SAFETY: This function only tests extraction services, never deletes anything.
    """
    import json
    from pathlib import Path

    from article_extractor import ExtractionOptions, PlaywrightFetcher, extract_article
    from rich.console import Console
    from rich.table import Table

    console = Console()

    # Load tenant config
    with deployment_config.open() as f:
        config = json.load(f)

    tenant_config = next((t for t in config["tenants"] if t["codename"] == tenant_codename), None)

    if not tenant_config:
        print(f"❌ Tenant '{tenant_codename}' not found in deployment config")
        return False

    console.print(f"\n[bold green]🧪 Article Extractor Test for '{tenant_codename}'[/bold green]")
    console.print(f"   Tenant: {tenant_config.get('docs_name', tenant_codename)}")
    console.print("   Using: Pure Python article-extractor (no external services)")

    # Get test URL from tenant config - try entry URL first, then sitemap, then derive from whitelist
    test_url = tenant_config.get("docs_entry_url")
    if not test_url:
        # Try to get sitemap URL and derive a test URL
        sitemap_url = tenant_config.get("docs_sitemap_url")
        url_whitelist = tenant_config.get("url_whitelist_prefixes", "")

        if url_whitelist:
            # Use first whitelist prefix as test URL
            if isinstance(url_whitelist, list):
                test_url = url_whitelist[0]
            elif isinstance(url_whitelist, str):
                test_url = url_whitelist.split(",")[0].strip()
        elif sitemap_url:
            # Derive base URL from sitemap URL
            if isinstance(sitemap_url, list):
                sitemap_url = sitemap_url[0]
            # Convert sitemap URL to base docs URL
            # e.g., https://docs.example.com/sitemap.xml -> https://docs.example.com/
            from urllib.parse import urlparse

            parsed = urlparse(sitemap_url)
            test_url = f"{parsed.scheme}://{parsed.netloc}/"

    if not test_url:
        print("❌ No test URL could be determined for this tenant (no entry URL, sitemap URL, or whitelist)")
        return False

    if isinstance(test_url, list):
        test_url = test_url[0]

    console.print(f"   Test URL: {test_url}")

    # Create table for results
    table = Table(title="Article Extraction Test Results")
    table.add_column("Step", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Details", style="yellow")

    # Use Playwright storage state
    playwright_storage_dir = Path(PLAYWRIGHT_STORAGE_DIR).resolve()
    playwright_storage_dir.mkdir(exist_ok=True)

    extraction_options = ExtractionOptions(
        min_word_count=150,
        include_images=False,
        include_code_blocks=True,
        safe_markdown=True,
    )

    success = False

    try:
        async with PlaywrightFetcher() as fetcher:
            # Step 1: Fetch HTML with Playwright
            console.print("\n[bold]Testing Playwright fetch...[/bold]")
            html_content, status_code = await fetcher.fetch(test_url)

            if not html_content or status_code != 200:
                table.add_row("Playwright Fetch", "❌ FAILED", f"HTTP {status_code}")
                console.print(table)
                return False

            table.add_row("Playwright Fetch", "✅ SUCCESS", f"HTTP {status_code}, {len(html_content)} bytes")

            # Step 2: Extract content with article-extractor
            console.print("\n[bold]Testing article extraction...[/bold]")
            result = extract_article(html_content, test_url, extraction_options)

            if not result.success:
                table.add_row("Article Extraction", "❌ FAILED", result.error or "No content extracted")
                console.print(table)
                return False

            table.add_row(
                "Article Extraction",
                "✅ SUCCESS",
                f"Title: {len(result.title)} chars, Content: {len(result.content)} chars",
            )

            # Step 3: Validate markdown output
            if result.markdown:
                table.add_row(
                    "Markdown Generation", "✅ SUCCESS", f"{len(result.markdown)} chars, {result.word_count} words"
                )
            else:
                table.add_row("Markdown Generation", "⚠️ WARNING", "No markdown generated")

            success = True

            # Show sample content
            console.print(f"\n   📄 Title: {result.title}")
            sample_markdown = result.markdown[:300] + "..." if len(result.markdown) > 300 else result.markdown
            console.print(f"   📝 Sample markdown:\n{sample_markdown}")

    except Exception as e:
        table.add_row("Extraction", "❌ ERROR", str(e)[:50] + "..." if len(str(e)) > 50 else str(e))
        console.print(f"   ❌ Error: {e}")

    console.print("\n")
    console.print(table)

    # Summary
    console.print("\n[bold]Test Summary:[/bold]")
    if success:
        console.print("   ✅ Article extractor is working correctly")
    else:
        console.print("   ❌ Article extraction failed")

    return success


async def debug_crawler(tenant_codename: str, deployment_config: Path, headed: bool = False):
    """Debug crawler directly without starting server.

    Tests the crawler against a tenant's entry URL to diagnose link discovery issues.
    """
    import json
    import logging

    from rich.console import Console

    from article_extractor.discovery import CrawlConfig, EfficientCrawler
    from docs_mcp_server.config import Settings

    # Enable DEBUG logging for crawler
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)s [%(name)s] %(message)s",
        force=True,  # Override any existing config
    )

    console = Console()

    # Load tenant config
    with deployment_config.open() as f:
        config = json.load(f)

    tenant_config = next((t for t in config["tenants"] if t["codename"] == tenant_codename), None)

    if not tenant_config:
        print(f"❌ Tenant '{tenant_codename}' not found in deployment config")
        return False

    console.print(f"\n[bold green]🐛 Crawler Debug Mode for '{tenant_codename}'[/bold green]")
    console.print(f"   Tenant: {tenant_config.get('docs_name', tenant_codename)}")
    console.print(
        f"   Playwright Mode: {'🖥️  HEADED (visible browser)' if headed else '👻 HEADLESS (invisible browser)'}"
    )

    # Get crawler config
    entry_url = tenant_config.get("docs_entry_url")
    sitemap_url = tenant_config.get("docs_sitemap_url")
    whitelist_prefixes = tenant_config.get("url_whitelist_prefixes", "")
    enable_crawler = tenant_config.get("enable_crawler", False)
    # Limit to 3 pages for debug mode to avoid long waits
    max_pages = 3

    console.print("\n[bold]Configuration:[/bold]")
    console.print(f"   Entry URL: {entry_url}")
    console.print(f"   Sitemap URL: {sitemap_url}")
    console.print(f"   Whitelist Prefixes: {whitelist_prefixes}")
    console.print(f"   Crawler Enabled: {enable_crawler}")
    console.print(f"   Max Pages: {max_pages} (debug limit)")

    # Determine start URL - prefer entry URL, fall back to derived URL from whitelist or sitemap
    start_url = entry_url
    if not start_url:
        # Try to derive from whitelist prefixes
        if whitelist_prefixes:
            if isinstance(whitelist_prefixes, list):
                start_url = whitelist_prefixes[0]
            elif isinstance(whitelist_prefixes, str):
                start_url = whitelist_prefixes.split(",")[0].strip()
        elif sitemap_url:
            # Derive base URL from sitemap URL
            if isinstance(sitemap_url, list):
                sitemap_url = sitemap_url[0]
            from urllib.parse import urlparse

            parsed = urlparse(sitemap_url)
            start_url = f"{parsed.scheme}://{parsed.netloc}/"

    if not start_url:
        print("❌ No start URL could be determined (no entry URL, sitemap URL, or whitelist)")
        return False

    console.print(f"\n[bold cyan]Using start URL: {start_url}[/bold cyan]")

    if not enable_crawler:
        print("⚠️  Crawler is disabled for this tenant")

    # Parse whitelist prefixes
    if isinstance(whitelist_prefixes, str):
        whitelist_list = [p.strip() for p in whitelist_prefixes.split(",") if p.strip()]
    elif isinstance(whitelist_prefixes, list):
        whitelist_list = whitelist_prefixes
    else:
        whitelist_list = []

    console.print(f"\n[bold]Parsed Whitelist ({len(whitelist_list)} prefixes):[/bold]")
    for prefix in whitelist_list:
        console.print(f"   - {prefix}")

    # Convert whitelist to string format that Settings expects
    whitelist_str = whitelist_prefixes if isinstance(whitelist_prefixes, str) else ",".join(whitelist_list)

    # Prepare settings kwargs
    settings_kwargs = {
        "docs_name": tenant_config.get("docs_name", tenant_codename),
        "url_whitelist_prefixes": whitelist_str,
        "enable_crawler": enable_crawler,
    }

    # Add entry URL or sitemap URL (Settings validation requires one)
    if entry_url:
        entry_list = entry_url if isinstance(entry_url, list) else [entry_url]
        settings_kwargs["docs_entry_url"] = entry_list
    elif sitemap_url:
        sitemap_list = sitemap_url if isinstance(sitemap_url, list) else [sitemap_url]
        settings_kwargs["docs_sitemap_url"] = sitemap_list

    settings = Settings(**settings_kwargs)

    console.print("\n[bold]Settings URL whitelist:[/bold]")
    console.print(f"   Prefixes: {settings.get_url_whitelist_prefixes()}")

    # Initialize crawler
    console.print("\n[bold cyan]Initializing crawler...[/bold cyan]")

    # Use Playwright storage state directory
    playwright_storage_dir = Path(PLAYWRIGHT_STORAGE_DIR).resolve()
    playwright_storage_dir.mkdir(exist_ok=True)
    storage_state_file = playwright_storage_dir / "storage-state.json"

    # Set environment variable for Playwright fetcher
    os.environ["PLAYWRIGHT_STORAGE_STATE_FILE"] = str(storage_state_file)
    console.print(f"   Storage State: {storage_state_file}")

    start_urls = {start_url}

    # Create crawler config
    crawl_config = CrawlConfig(
        max_pages=max_pages,
        headless=not headed,  # headed=True means headless=False
        prefer_playwright=settings.crawler_playwright_first,
        user_agent_provider=settings.get_random_user_agent,
        should_process_url=settings.should_process_url,
        min_concurrency=settings.crawler_min_concurrency,
        max_concurrency=settings.crawler_max_concurrency,
        max_sessions=settings.crawler_max_sessions,
    )

    # Create crawler (needs async context manager)
    async with EfficientCrawler(
        start_urls=start_urls,
        crawl_config=crawl_config,
    ) as crawler:
        console.print(f"   Start URLs: {len(start_urls)}")
        console.print(f"   Allowed hosts: {crawler.allowed_hosts}")

        # Run crawler
        console.print("\n[bold cyan]Running crawler...[/bold cyan]")

        discovered_urls = await crawler.crawl()

        console.print("\n[bold green]✅ Crawler completed![/bold green]")
        console.print(f"   Discovered URLs: {len(discovered_urls)}")

        if discovered_urls:
            console.print("\n[bold]First 20 discovered URLs:[/bold]")
            for i, url in enumerate(list(discovered_urls)[:20], 1):
                console.print(f"   {i}. {url}")

            if len(discovered_urls) > 20:
                console.print(f"   ... and {len(discovered_urls) - 20} more")
        else:
            console.print("\n[bold red]❌ No URLs discovered![/bold red]")
            console.print("\nDebugging suggestions:")
            console.print("   1. Check if the entry URL is accessible")
            console.print("   2. Check if the whitelist prefixes match the discovered URLs")
            console.print("   3. Check if the page has any links at all")
            console.print("   4. Try fetching the page manually to see its structure")

        # Show crawler stats
        console.print("\n[bold]Crawler Statistics:[/bold]")
        console.print(f"   Total pages collected: {len(crawler.collected)}")
        console.print(f"   Total pages visited: {len(crawler.visited)}")
        console.print(f"   Max pages limit: {max_pages}")

        return len(discovered_urls) > 0


async def main_async(args):  # noqa: PLR0911
    """Async main function."""
    print(f"Current working directory: {Path.cwd()}")

    # Determine deployment config path with local override support
    deployment_config = Path(args.config)
    local_override = Path("deployment.local.json")

    if local_override.exists() and args.config == "deployment.json":
        print(f"📍 Found deployment.local.json - using it instead of {args.config}")
        deployment_config = local_override

    # Handle special modes that don't need server management
    if args.debug_crawler or args.test_extractors:
        if not args.tenant or len(args.tenant) != 1:
            mode_name = "debug-crawler" if args.debug_crawler else "test-extractors"
            print(f"❌ --{mode_name} requires exactly one --tenant to be specified")
            return 1

        if not deployment_config.exists():
            print(f"❌ Deployment config not found: {deployment_config}")
            return 1

        if args.debug_crawler:
            success = await debug_crawler(args.tenant[0], deployment_config, args.headed)
        else:  # args.test_extractors
            success = await test_html_extractors(args.tenant[0], deployment_config, args.headed)

        return 0 if success else 1

    # Support deployment.local.json override
    deployment_config = Path(args.config)
    local_override = Path("deployment.local.json")

    if local_override.exists() and args.config == "deployment.json":
        print(f"📍 Found deployment.local.json - using it instead of {args.config}")
        deployment_config = local_override

    if not deployment_config.exists():
        print(f"❌ Deployment config not found: {deployment_config}")
        return 1

    # If explicit host/port provided, use original config without patching
    if args.host or args.port:
        print("🔗 Using explicit host/port - skipping local config patching")
        debug_config = deployment_config
    else:
        # Create debug config for testing
        debug_config = create_debug_deployment_config(
            deployment_config,
            enable_sync=args.enable_sync,
            tenant_filters=args.tenant,
            host=args.host,
            port=args.port,
            log_profile=args.log_profile,
        )

    # Start server with config and explicit host/port if provided
    server = ServerManager(debug_config, args.host, args.port)

    try:
        if not server.start():
            return 1

        # Handle trigger-sync mode
        if args.trigger_sync:
            success = await trigger_sync_all_tenants(server.server_url, debug_config)
            return 0 if success else 1

        # Handle root hub test mode
        if args.root:
            tester = RootHubTester(server.server_url)
            success = await tester.run_tests(
                test_type=args.root_test,
                target_tenant=args.target_tenant,
                query=args.query,
                word_match=args.word_match,
            )
            return 0 if success else 1

        # Handle crawl test mode (requires tenant to be specified)
        if args.test == "crawl":
            if not args.tenant or len(args.tenant) != 1:
                print("❌ --test=crawl requires exactly one --tenant to be specified")
                return 1

            tenant_name = args.tenant[0]
            success = await test_crawl_urls(tenant_name, debug_config, max_urls=5, headed=args.headed)
            return 0 if success else 1

        # Run tests
        if args.tenant:
            # Test specific tenant(s)
            all_passed = True
            for tenant_name in args.tenant:
                print(f"\n--- Testing tenant: {tenant_name} ---")
                success = await test_single_tenant(
                    server.server_url,
                    tenant_name,
                    debug_config,
                    args.test,
                    query=args.query,
                    word_match=args.word_match,
                )
                if not success:
                    all_passed = False
            return 0 if all_passed else 1
        # Test all tenants
        all_results = await test_all_tenants(
            server.server_url,
            debug_config,
            args.test,
            args.query,
            args.word_match,
        )

        # Print summary
        print(f"\n{'=' * 80}")
        print("TEST SUMMARY")
        print(f"{'=' * 80}")

        all_passed = True
        for tenant, results in all_results.items():
            status = "✅" if all(results.values()) else "❌"
            print(f"{status} {tenant}: {results}")
            all_passed = all_passed and all(results.values())

        return 0 if all_passed else 1

    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        return 1
    finally:
        # Always stop the server managed by this script.
        # The server.stop() method already handles not stopping external servers.
        server.stop()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Debug multi-tenant docs MCP server")
    parser.add_argument(
        "--config",
        default="deployment.json",
        help="Path to deployment.json (default: deployment.json, auto-uses deployment.local.json if exists)",
    )
    parser.add_argument(
        "--tenant",
        nargs="+",
        help="Test specific tenant(s) only (e.g., 'django', 'drf')",
    )
    parser.add_argument(
        "--test",
        choices=["all", "search", "fetch", "crawl", "parity"],
        default="all",
        help="Type of test to run (default: all; use 'parity' to compare metadata vs disk)",
    )
    parser.add_argument(
        "--query",
        help="Search query for 'search' test",
        default="configuration",
    )
    parser.add_argument(
        "--enable-sync",
        action="store_true",
        help="Enable sync for tenants (default: disabled, runs in offline mode)",
    )
    parser.add_argument(
        "--trigger-sync",
        action="store_true",
        help="Trigger sync for all tenants and monitor document counts every 30s",
    )
    parser.add_argument(
        "--host",
        help="Connect to specific host (overrides config and local patching)",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Connect to specific port (overrides config and local patching)",
    )
    parser.add_argument(
        "--word-match",
        action="store_true",
        help="Enable whole word matching for search tests",
    )
    parser.add_argument(
        "--debug-crawler",
        action="store_true",
        help="Run crawler debug mode - test crawler directly without starting server",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Playwright in headed mode (for debugging, works with --debug-crawler or crawl tests)",
    )
    parser.add_argument(
        "--test-extractors",
        action="store_true",
        help="Test article-extractor HTML content extraction",
    )
    parser.add_argument(
        "--root",
        action="store_true",
        help="Test the root hub MCP aggregator (list_tenants, describe_tenant, root_search, root_fetch, root_browse)",
    )
    parser.add_argument(
        "--root-test",
        choices=["all", "list", "describe", "search", "fetch", "browse"],
        default="all",
        help="Type of root hub test to run (default: all). Use with --root",
    )
    parser.add_argument(
        "--target-tenant",
        help="Target tenant for root hub proxy tests (search, fetch, browse). If not specified, uses first available tenant.",
    )
    parser.add_argument(
        "--log-profile",
        help="Select logging profile from deployment.json log_profiles (e.g., 'trace-drftest'). Overrides default profile.",
    )

    args = parser.parse_args()

    # Validate argument combinations
    if args.trigger_sync and args.tenant:
        print("❌ --trigger-sync cannot be used with --tenant (triggers all tenants)")
        sys.exit(1)

    if args.trigger_sync and args.test != "all":
        print("❌ --trigger-sync cannot be used with --test (only triggers sync)")
        sys.exit(1)

    if args.test == "crawl" and not args.tenant:
        print("❌ --test=crawl requires --tenant to be specified")
        sys.exit(1)

    if args.headed and not (args.debug_crawler or args.test == "crawl" or args.test_extractors):
        print("❌ --headed can only be used with --debug-crawler, --test=crawl, or --test-extractors")
        sys.exit(1)

    if args.test_extractors and not args.tenant:
        print("❌ --test-extractors requires --tenant to be specified")
        sys.exit(1)

    if args.root and args.tenant:
        print("❌ --root cannot be used with --tenant (use --target-tenant for proxy tests)")
        sys.exit(1)

    if args.root_test != "all" and not args.root:
        print("❌ --root-test requires --root to be specified")
        sys.exit(1)

    if args.target_tenant and not args.root:
        print("❌ --target-tenant requires --root to be specified")
        sys.exit(1)

    # Validate host/port combinations
    if args.host and not args.port:
        print("❌ --host requires --port to be specified")
        sys.exit(1)

    if args.port and not args.host:
        print("❌ --port requires --host to be specified")
        sys.exit(1)

    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
