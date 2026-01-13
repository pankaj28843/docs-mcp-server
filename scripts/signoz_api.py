#!/usr/bin/env python3
"""Shared helpers for SigNoz provisioning scripts."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


DEFAULT_BASE_URL = os.environ.get("SIGNOZ_BASE_URL", "http://localhost:8080")
DEFAULT_TIMEOUT_SECONDS = 15


class SignozError(RuntimeError):
    pass


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _build_headers(api_key: str | None, token: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["SigNoz-Api-Key"] = api_key
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def request_json(
    method: str,
    base_url: str,
    path: str,
    *,
    payload: dict | list | None = None,
    api_key: str | None = None,
    token: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    url = f"{_normalize_base_url(base_url)}{path}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_build_headers(api_key, token), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            body = resp.read().decode("utf-8")
            if not body:
                return None
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise SignozError(f"HTTP {exc.code} for {method} {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise SignozError(f"Failed to reach SigNoz at {url}: {exc}") from exc


def create_session_token(base_url: str, email: str, password: str) -> str:
    response = request_json(
        "POST",
        base_url,
        "/api/v2/sessions/email_password",
        payload={"email": email, "password": password},
    )
    token = response.get("data", {}).get("accessToken")
    if not token:
        raise SignozError("SigNoz session token missing in response")
    return token


def list_dashboards(base_url: str, api_key: str | None, token: str | None) -> list[dict]:
    response = request_json("GET", base_url, "/api/v1/dashboards", api_key=api_key, token=token)
    return response.get("data", []) if isinstance(response, dict) else []


def create_dashboard(base_url: str, data: dict, api_key: str | None, token: str | None) -> dict:
    response = request_json("POST", base_url, "/api/v1/dashboards", payload=data, api_key=api_key, token=token)
    return response.get("data", {}) if isinstance(response, dict) else {}


def update_dashboard(base_url: str, dashboard_id: str, data: dict, api_key: str | None, token: str | None) -> dict:
    response = request_json(
        "PUT",
        base_url,
        f"/api/v1/dashboards/{dashboard_id}",
        payload=data,
        api_key=api_key,
        token=token,
    )
    return response.get("data", {}) if isinstance(response, dict) else {}


def list_rules(base_url: str, api_key: str | None, token: str | None) -> list[dict]:
    response = request_json("GET", base_url, "/api/v1/rules", api_key=api_key, token=token)
    if isinstance(response, dict):
        return response.get("data", {}).get("rules", [])
    return []


def create_rule(base_url: str, data: dict, api_key: str | None, token: str | None) -> dict:
    response = request_json("POST", base_url, "/api/v1/rules", payload=data, api_key=api_key, token=token)
    return response.get("data", {}) if isinstance(response, dict) else {}


def update_rule(base_url: str, rule_id: str, data: dict, api_key: str | None, token: str | None) -> dict:
    response = request_json(
        "PUT",
        base_url,
        f"/api/v1/rules/{rule_id}",
        payload=data,
        api_key=api_key,
        token=token,
    )
    return response.get("data", {}) if isinstance(response, dict) else {}


def list_api_keys(base_url: str, api_key: str | None, token: str | None) -> list[dict]:
    response = request_json("GET", base_url, "/api/v1/pats", api_key=api_key, token=token)
    if isinstance(response, dict):
        return response.get("data", [])
    return []


def create_api_key(
    base_url: str,
    name: str,
    role: str,
    expires_in_days: int,
    api_key: str | None,
    token: str | None,
) -> dict:
    payload = {"name": name, "role": role, "expiresInDays": expires_in_days}
    response = request_json("POST", base_url, "/api/v1/pats", payload=payload, api_key=api_key, token=token)
    return response.get("data", {}) if isinstance(response, dict) else {}

def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_auth(base_url: str, api_key: str | None, email: str | None, password: str | None) -> tuple[str | None, str | None]:
    if api_key:
        return api_key, None
    if email and password:
        return None, create_session_token(base_url, email, password)
    raise SignozError("Provide SIGNOZ_API_KEY or SIGNOZ_EMAIL/SIGNOZ_PASSWORD for SigNoz auth")


def write_stderr(message: str) -> None:
    sys.stderr.write(message + "\n")
