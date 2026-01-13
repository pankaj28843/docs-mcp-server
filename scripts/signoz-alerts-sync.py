#!/usr/bin/env python3
"""Sync SigNoz alert rules from JSON files."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from signoz_api import (
    SignozError,
    list_rules,
    load_json,
    resolve_auth,
    create_rule,
    update_rule,
    write_stderr,
)


def _index_rules(rules: list[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for rule in rules:
        name = rule.get("alert")
        if name:
            index[name] = rule
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync SigNoz alert rules from JSON files.")
    parser.add_argument("--base-url", default=os.environ.get("SIGNOZ_BASE_URL", "http://localhost:8080"))
    parser.add_argument("--alerts-dir", default="observability/signoz/alerts")
    parser.add_argument("--api-key", default=os.environ.get("SIGNOZ_API_KEY"))
    parser.add_argument("--email", default=os.environ.get("SIGNOZ_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("SIGNOZ_PASSWORD"))
    parser.add_argument("--dry-run", action="store_true", help="Only print planned changes")
    args = parser.parse_args()

    try:
        api_key, token = resolve_auth(args.base_url, args.api_key, args.email, args.password)
        rules = list_rules(args.base_url, api_key, token)
        by_name = _index_rules(rules)

        alerts_dir = Path(args.alerts_dir)
        if not alerts_dir.exists():
            write_stderr(f"Alerts dir not found: {alerts_dir}")
            return 1

        for alert_path in sorted(alerts_dir.glob("*.json")):
            payload = load_json(str(alert_path))
            name = payload.get("alert")
            if not name:
                write_stderr(f"Missing alert name in {alert_path}")
                return 1

            existing = by_name.get(name)
            if existing:
                rule_id = existing.get("id")
                if not rule_id:
                    write_stderr(f"Missing id for existing alert {name}")
                    return 1
                print(f"Update alert: {name} ({rule_id})")
                if not args.dry_run:
                    update_rule(args.base_url, rule_id, payload, api_key, token)
            else:
                print(f"Create alert: {name}")
                if not args.dry_run:
                    create_rule(args.base_url, payload, api_key, token)

    except SignozError as exc:
        write_stderr(str(exc))
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
