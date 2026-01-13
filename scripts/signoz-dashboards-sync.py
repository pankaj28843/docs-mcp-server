#!/usr/bin/env python3
"""Sync SigNoz dashboards from JSON files."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from signoz_api import (
    SignozError,
    list_dashboards,
    load_json,
    resolve_auth,
    create_dashboard,
    update_dashboard,
    write_stderr,
)


def _index_dashboards(dashboards: list[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for dashboard in dashboards:
        data = dashboard.get("data") or {}
        title = data.get("title")
        if title:
            index[title] = dashboard
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync SigNoz dashboards from JSON files.")
    parser.add_argument("--base-url", default=os.environ.get("SIGNOZ_BASE_URL", "http://localhost:8080"))
    parser.add_argument("--dashboards-dir", default="observability/signoz/dashboards")
    parser.add_argument("--api-key", default=os.environ.get("SIGNOZ_API_KEY"))
    parser.add_argument("--email", default=os.environ.get("SIGNOZ_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("SIGNOZ_PASSWORD"))
    parser.add_argument("--dry-run", action="store_true", help="Only print planned changes")
    args = parser.parse_args()

    try:
        api_key, token = resolve_auth(args.base_url, args.api_key, args.email, args.password)
        dashboards = list_dashboards(args.base_url, api_key, token)
        by_title = _index_dashboards(dashboards)

        dashboards_dir = Path(args.dashboards_dir)
        if not dashboards_dir.exists():
            write_stderr(f"Dashboards dir not found: {dashboards_dir}")
            return 1

        for dashboard_path in sorted(dashboards_dir.glob("*.json")):
            payload = load_json(str(dashboard_path))
            title = payload.get("title")
            if not title:
                write_stderr(f"Missing title in {dashboard_path}")
                return 1

            existing = by_title.get(title)
            if existing:
                dashboard_id = existing.get("id")
                if not dashboard_id:
                    write_stderr(f"Missing id for existing dashboard {title}")
                    return 1
                print(f"Update dashboard: {title} ({dashboard_id})")
                if not args.dry_run:
                    update_dashboard(args.base_url, dashboard_id, payload, api_key, token)
            else:
                print(f"Create dashboard: {title}")
                if not args.dry_run:
                    create_dashboard(args.base_url, payload, api_key, token)

    except SignozError as exc:
        write_stderr(str(exc))
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
