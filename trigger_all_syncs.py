#!/usr/bin/env python3
"""Trigger sync for all or specific online tenants dynamically.

This script queries the health endpoint to discover all online tenants
(those with active schedulers) and triggers a sync for each one.
You can filter tenants by codename to sync only specific tenants.

Usage:
    uv run python trigger_all_syncs.py [--host HOST] [--port PORT] [--tenants TENANT1 TENANT2 ...] [--force]

Examples:
    # Sync all online tenants (default, respects idempotency - skips recently fetched)
    uv run python trigger_all_syncs.py

    # Force sync all tenants (ignores idempotency, crawls everything)
    uv run python trigger_all_syncs.py --force

    # Sync specific tenants only
    uv run python trigger_all_syncs.py --tenants django drf

    # Force sync specific tenants
    uv run python trigger_all_syncs.py --tenants django drf --force

    # Sync django-extensions tenant on custom host/port
    uv run python trigger_all_syncs.py --host localhost --port 8000 --tenants django-extensions

    # Multiple tenants with custom server (force mode)
    uv run python trigger_all_syncs.py --host localhost --port 42042 --tenants django fastapi python --force
"""

# ruff: noqa: T201
import argparse
import sys
from typing import Any

import httpx


def get_online_tenants(base_url: str, filter_tenants: list[str] | None = None) -> list[dict[str, Any]]:
    """Fetch all online tenants from the health endpoint, optionally filtered.

    Args:
        base_url: Base URL of the MCP server (e.g., http://localhost:42042)
        filter_tenants: Optional list of tenant codenames to filter by

    Returns:
        List of tenant info dicts with 'codename' and 'name' keys
    """
    health_url = f"{base_url}/health"
    try:
        response = httpx.get(health_url, timeout=10.0)
        response.raise_for_status()
        health_data = response.json()

        tenants = health_data.get("tenants", {})
        online_tenants = []
        for codename, tenant_data in tenants.items():
            if filter_tenants and codename not in filter_tenants:
                continue

            scheduler_state = tenant_data.get("scheduler")
            source_type = (tenant_data.get("source_type") or "").lower()

            # Legacy deployments reported scheduler state; default to running when available.
            if scheduler_state is not None:
                is_syncable = scheduler_state == "running"
            else:
                # Embedded worker mode: treat online and git tenants as syncable, skip filesystem-only tenants.
                is_syncable = source_type in {"online", "git"}

            if not is_syncable:
                continue

            online_tenants.append(
                {
                    "codename": codename,
                    "name": tenant_data.get("name", codename),
                    "documents": tenant_data.get("documents", 0),
                    "source_type": source_type,
                }
            )

        return online_tenants

    except httpx.HTTPStatusError as e:
        print(f"HTTP error fetching health endpoint: {e}", file=sys.stderr)
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"Request error fetching health endpoint: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error fetching health endpoint: {e}", file=sys.stderr)
        sys.exit(1)


def trigger_sync(base_url: str, tenant_codename: str, force: bool = False) -> dict[str, Any]:
    """Trigger sync for a specific tenant.

    Args:
        base_url: Base URL of the MCP server
        tenant_codename: Tenant codename to sync
        force: If True, ignore idempotency and crawl everything

    Returns:
        Response JSON from the sync trigger endpoint
    """
    sync_url = f"{base_url}/{tenant_codename}/sync/trigger"
    if force:
        sync_url += "?force_crawler=true&force_full_sync=true"
    try:
        response = httpx.post(sync_url, timeout=10.0)
        # Parse JSON response even for 4xx status codes (server returns valid JSON)
        try:
            result = response.json()
        except Exception:
            result = {"message": response.text}

        # If success field is present, use it; otherwise use HTTP status
        if "success" not in result:
            result["success"] = response.status_code < 400

        return result
    except httpx.RequestError as e:
        return {"success": False, "error": str(e), "message": "Failed to connect"}


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Trigger sync for all or specific online tenants",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="MCP server host (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=42042,
        help="MCP server port (default: 42042)",
    )
    parser.add_argument(
        "--tenants",
        nargs="+",
        metavar="TENANT",
        help="Filter to specific tenant codenames (e.g., django drf fastapi)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force sync: ignore idempotency and crawl all URLs (default: respect idempotency)",
    )
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"

    print("=== Triggering sync for online tenants ===")
    print(f"Server: {base_url}")
    if args.tenants:
        print(f"Filter: {', '.join(args.tenants)}")
    else:
        print("Filter: None (all tenants)")
    print(
        f"Force:  {args.force} "
        f"{'(forces crawl + full sync)' if args.force else '(respects idempotency)'}"
    )
    print()

    # Get all online tenants (optionally filtered)
    online_tenants = get_online_tenants(base_url, args.tenants)

    if not online_tenants:
        if args.tenants:
            print(f"No online tenants found matching: {', '.join(args.tenants)}")
            print("Check tenant codenames and ensure they are online with active schedulers.")
        else:
            print("No online tenants found!")
        return

    print(f"Found {len(online_tenants)} online tenant(s):\n")

    # Trigger sync for each tenant
    success_count = 0
    already_running_count = 0
    failed_count = 0

    for tenant in online_tenants:
        codename = tenant["codename"]

        # Print tenant info with fixed width
        print(f"{codename:<30} ", end="", flush=True)

        result = trigger_sync(base_url, codename, force=args.force)
        message = result.get("message", "Unknown response")

        # Colorize output based on result
        if "error" in result:
            print(f"❌ {message}")
            failed_count += 1
        elif "already in progress" in message.lower():
            print(f"⏳ {message}")
            already_running_count += 1
        else:
            print(f"✅ {message}")
            success_count += 1

    # Print summary
    print("\n" + "=" * 70)
    print("Summary:")
    print(f"  Total tenants:     {len(online_tenants)}")
    print(f"  Sync triggered:    {success_count}")
    print(f"  Already running:   {already_running_count}")
    print(f"  Failed:            {failed_count}")
    print("=" * 70)


if __name__ == "__main__":
    main()
