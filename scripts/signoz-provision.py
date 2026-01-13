#!/usr/bin/env python3
"""Provision SigNoz resources (API key, dashboards, alerts)."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

from signoz_api import (
    SignozError,
    create_api_key,
    create_session_token,
    list_api_keys,
    resolve_auth,
    write_stderr,
)


def _run_script(args: list[str]) -> None:
    subprocess.run([sys.executable, *args], check=True)


def _resolve_api_key(
    base_url: str,
    api_key: str | None,
    email: str | None,
    password: str | None,
    ensure_api_key: bool,
    key_name: str,
    key_role: str,
    key_expiry_days: int,
) -> str | None:
    if api_key:
        return api_key

    if not ensure_api_key:
        return None

    if not email or not password:
        raise SignozError("SIGNOZ_EMAIL and SIGNOZ_PASSWORD are required to create an API key")

    token = create_session_token(base_url, email, password)
    existing_keys = list_api_keys(base_url, api_key=None, token=token)
    for key in existing_keys:
        if key.get("name") == key_name and not key.get("revoked"):
            token_value = key.get("token")
            if token_value:
                print(f"Using existing API key: {key_name}")
                return token_value

    created = create_api_key(
        base_url,
        name=key_name,
        role=key_role,
        expires_in_days=key_expiry_days,
        api_key=None,
        token=token,
    )
    token_value = created.get("token")
    if not token_value:
        raise SignozError("Created API key did not return a token")
    print(f"Created API key: {key_name}")
    return token_value


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision SigNoz resources.")
    parser.add_argument("--base-url", default=os.environ.get("SIGNOZ_BASE_URL", "http://localhost:8080"))
    parser.add_argument("--api-key", default=os.environ.get("SIGNOZ_API_KEY"))
    parser.add_argument("--email", default=os.environ.get("SIGNOZ_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("SIGNOZ_PASSWORD"))
    parser.add_argument("--ensure-api-key", action="store_true")
    parser.add_argument("--api-key-name", default="docs-mcp-server-automation")
    parser.add_argument("--api-key-role", default="ADMIN")
    parser.add_argument("--api-key-expiry-days", type=int, default=0)
    parser.add_argument("--dashboards-dir", default="observability/signoz/dashboards")
    parser.add_argument("--alerts-dir", default="observability/signoz/alerts")
    parser.add_argument("--skip-dashboards", action="store_true")
    parser.add_argument("--skip-alerts", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        api_key = _resolve_api_key(
            args.base_url,
            args.api_key,
            args.email,
            args.password,
            args.ensure_api_key,
            args.api_key_name,
            args.api_key_role,
            args.api_key_expiry_days,
        )
        if not api_key:
            resolve_auth(args.base_url, args.api_key, args.email, args.password)

        dashboards_dir = Path(args.dashboards_dir)
        alerts_dir = Path(args.alerts_dir)

        if not args.skip_dashboards:
            dashboard_args = [
                "scripts/signoz-dashboards-sync.py",
                "--base-url",
                args.base_url,
                "--dashboards-dir",
                str(dashboards_dir),
            ]
            if api_key:
                dashboard_args.extend(["--api-key", api_key])
            if args.dry_run:
                dashboard_args.append("--dry-run")
            _run_script(dashboard_args)

        if not args.skip_alerts:
            alert_args = [
                "scripts/signoz-alerts-sync.py",
                "--base-url",
                args.base_url,
                "--alerts-dir",
                str(alerts_dir),
            ]
            if api_key:
                alert_args.extend(["--api-key", api_key])
            if args.dry_run:
                alert_args.append("--dry-run")
            _run_script(alert_args)

    except SignozError as exc:
        write_stderr(str(exc))
        return 1
    except subprocess.CalledProcessError as exc:
        write_stderr(f"Provisioning step failed: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
