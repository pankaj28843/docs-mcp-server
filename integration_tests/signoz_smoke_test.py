#!/usr/bin/env python3
"""SigNoz integration smoke test (optional)."""
# ruff: noqa: T201

from __future__ import annotations

import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).parent.parent
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from signoz_api import SignozError, list_dashboards, list_rules, resolve_auth


def main() -> int:
    if os.environ.get("SIGNOZ_SMOKE") != "1":
        print("Skipping SigNoz smoke test (set SIGNOZ_SMOKE=1 to enable).")
        return 0

    base_url = os.environ.get("SIGNOZ_BASE_URL", "http://localhost:8080")
    api_key = os.environ.get("SIGNOZ_API_KEY")
    email = os.environ.get("SIGNOZ_EMAIL")
    password = os.environ.get("SIGNOZ_PASSWORD")

    try:
        resolved_api_key, token = resolve_auth(base_url, api_key, email, password)
        dashboards = list_dashboards(base_url, resolved_api_key, token)
        rules = list_rules(base_url, resolved_api_key, token)
        print(f"SigNoz dashboards visible: {len(dashboards)}")
        print(f"SigNoz rules visible: {len(rules)}")
    except SignozError as exc:
        print(f"SigNoz smoke test failed: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
