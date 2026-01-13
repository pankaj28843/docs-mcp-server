"""Unit tests for SigNoz provisioning scripts."""

from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path
import sys
import types
from typing import Any
import urllib.error

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import importlib.util  # noqa: E402

import signoz_api  # noqa: E402


def _load_script(name: str, filename: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module


signoz_alerts_sync = _load_script("signoz_alerts_sync", "signoz-alerts-sync.py")
signoz_dashboards_sync = _load_script("signoz_dashboards_sync", "signoz-dashboards-sync.py")
signoz_provision = _load_script("signoz_provision", "signoz-provision.py")


@dataclass
class _FakeResponse:
    payload: bytes

    def read(self) -> bytes:
        return self.payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.mark.unit
class TestSignozApi:
    def test_normalize_base_url(self):
        assert signoz_api._normalize_base_url("http://localhost:8080/") == "http://localhost:8080"

    def test_build_headers(self):
        headers = signoz_api._build_headers("api-key", "token")
        assert headers["Content-Type"] == "application/json"
        assert headers["SigNoz-Api-Key"] == "api-key"
        assert headers["Authorization"] == "Bearer token"

    def test_request_json_returns_none_on_empty_body(self, monkeypatch):
        def fake_urlopen(*_args, **_kwargs):
            return _FakeResponse(b"")

        monkeypatch.setattr(signoz_api.urllib.request, "urlopen", fake_urlopen)
        assert signoz_api.request_json("GET", "http://localhost:8080", "/health") is None

    def test_request_json_parses_json(self, monkeypatch):
        def fake_urlopen(*_args, **_kwargs):
            return _FakeResponse(b'{"status": "ok"}')

        monkeypatch.setattr(signoz_api.urllib.request, "urlopen", fake_urlopen)
        assert signoz_api.request_json("GET", "http://localhost:8080", "/health") == {"status": "ok"}

    def test_request_json_handles_http_error(self, monkeypatch):
        def fake_urlopen(*_args, **_kwargs):
            raise urllib.error.HTTPError(
                url="http://localhost:8080/api",
                code=400,
                msg="bad",
                hdrs=None,
                fp=io.BytesIO(b'{"error":"bad"}'),
            )

        monkeypatch.setattr(signoz_api.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(signoz_api.SignozError, match="HTTP 400"):
            signoz_api.request_json("GET", "http://localhost:8080", "/api")

    def test_request_json_handles_url_error(self, monkeypatch):
        def fake_urlopen(*_args, **_kwargs):
            raise urllib.error.URLError("down")

        monkeypatch.setattr(signoz_api.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(signoz_api.SignozError, match="Failed to reach SigNoz"):
            signoz_api.request_json("GET", "http://localhost:8080", "/api")

    def test_create_session_token_missing(self, monkeypatch):
        def fake_request(*_args, **_kwargs):
            return {"data": {}}

        monkeypatch.setattr(signoz_api, "request_json", fake_request)
        with pytest.raises(signoz_api.SignozError, match="session token"):
            signoz_api.create_session_token("http://localhost:8080", "user@example.com", "pw")

    def test_resolve_auth_prefers_api_key(self):
        api_key, token = signoz_api.resolve_auth("http://localhost:8080", "key", None, None)
        assert api_key == "key"
        assert token is None

    def test_load_json(self, tmp_path):
        payload = {"title": "Dashboard"}
        path = tmp_path / "payload.json"
        path.write_text('{"title": "Dashboard"}')
        assert signoz_api.load_json(str(path)) == payload


@pytest.mark.unit
class TestDashboardsSync:
    def test_missing_dashboards_dir(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(signoz_dashboards_sync, "resolve_auth", lambda *_args, **_kwargs: ("key", None))
        monkeypatch.setattr(signoz_dashboards_sync, "list_dashboards", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(sys, "argv", ["signoz-dashboards-sync", "--dashboards-dir", str(tmp_path / "nope")])
        assert signoz_dashboards_sync.main() == 1
        assert "Dashboards dir not found" in capsys.readouterr().err

    def test_create_dashboard(self, monkeypatch, tmp_path):
        payload = {"title": "docs-mcp-server Overview"}
        (tmp_path / "overview.json").write_text('{"title": "docs-mcp-server Overview"}')

        created: list[dict[str, Any]] = []

        monkeypatch.setattr(signoz_dashboards_sync, "resolve_auth", lambda *_args, **_kwargs: ("key", None))
        monkeypatch.setattr(signoz_dashboards_sync, "list_dashboards", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(signoz_dashboards_sync, "create_dashboard", lambda *_args, **_kwargs: created.append(payload))
        monkeypatch.setattr(sys, "argv", ["signoz-dashboards-sync", "--dashboards-dir", str(tmp_path)])

        assert signoz_dashboards_sync.main() == 0
        assert created == [payload]

    def test_update_dashboard(self, monkeypatch, tmp_path):
        payload = {"title": "docs-mcp-server Overview"}
        (tmp_path / "overview.json").write_text('{"title": "docs-mcp-server Overview"}')

        updated: list[tuple[str, dict[str, Any]]] = []

        existing = [{"id": "dash-1", "data": {"title": "docs-mcp-server Overview"}}]
        monkeypatch.setattr(signoz_dashboards_sync, "resolve_auth", lambda *_args, **_kwargs: ("key", None))
        monkeypatch.setattr(signoz_dashboards_sync, "list_dashboards", lambda *_args, **_kwargs: existing)
        monkeypatch.setattr(
            signoz_dashboards_sync,
            "update_dashboard",
            lambda _base, dash_id, data, *_args, **_kwargs: updated.append((dash_id, data)),
        )
        monkeypatch.setattr(sys, "argv", ["signoz-dashboards-sync", "--dashboards-dir", str(tmp_path)])

        assert signoz_dashboards_sync.main() == 0
        assert updated == [("dash-1", payload)]


@pytest.mark.unit
class TestAlertsSync:
    def test_missing_alerts_dir(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(signoz_alerts_sync, "resolve_auth", lambda *_args, **_kwargs: ("key", None))
        monkeypatch.setattr(signoz_alerts_sync, "list_rules", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(sys, "argv", ["signoz-alerts-sync", "--alerts-dir", str(tmp_path / "nope")])
        assert signoz_alerts_sync.main() == 1
        assert "Alerts dir not found" in capsys.readouterr().err

    def test_create_alert(self, monkeypatch, tmp_path):
        payload = {"alert": "Latency critical"}
        (tmp_path / "latency.json").write_text('{"alert": "Latency critical"}')

        created: list[dict[str, Any]] = []
        monkeypatch.setattr(signoz_alerts_sync, "resolve_auth", lambda *_args, **_kwargs: ("key", None))
        monkeypatch.setattr(signoz_alerts_sync, "list_rules", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(signoz_alerts_sync, "create_rule", lambda *_args, **_kwargs: created.append(payload))
        monkeypatch.setattr(sys, "argv", ["signoz-alerts-sync", "--alerts-dir", str(tmp_path)])

        assert signoz_alerts_sync.main() == 0
        assert created == [payload]


@pytest.mark.unit
class TestSignozProvision:
    def test_resolve_api_key_returns_existing(self, monkeypatch):
        assert (
            signoz_provision._resolve_api_key(
                "http://localhost:8080",
                "existing",
                None,
                None,
                ensure_api_key=True,
                key_name="name",
                key_role="ADMIN",
                key_expiry_days=0,
            )
            == "existing"
        )

    def test_resolve_api_key_requires_credentials(self):
        with pytest.raises(signoz_api.SignozError, match="SIGNOZ_EMAIL"):
            signoz_provision._resolve_api_key(
                "http://localhost:8080",
                None,
                None,
                None,
                ensure_api_key=True,
                key_name="name",
                key_role="ADMIN",
                key_expiry_days=0,
            )

    def test_resolve_api_key_uses_existing_key(self, monkeypatch, capsys):
        monkeypatch.setattr(signoz_provision, "create_session_token", lambda *_args, **_kwargs: "token")
        monkeypatch.setattr(
            signoz_provision,
            "list_api_keys",
            lambda *_args, **_kwargs: [{"name": "docs-mcp-server-automation", "token": "abc", "revoked": False}],
        )
        token = signoz_provision._resolve_api_key(
            "http://localhost:8080",
            None,
            "user@example.com",
            "pw",
            ensure_api_key=True,
            key_name="docs-mcp-server-automation",
            key_role="ADMIN",
            key_expiry_days=0,
        )
        assert token == "abc"
        assert "Using existing API key" in capsys.readouterr().out

    def test_resolve_api_key_creates_key(self, monkeypatch, capsys):
        monkeypatch.setattr(signoz_provision, "create_session_token", lambda *_args, **_kwargs: "token")
        monkeypatch.setattr(signoz_provision, "list_api_keys", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(signoz_provision, "create_api_key", lambda *_args, **_kwargs: {"token": "new"})
        token = signoz_provision._resolve_api_key(
            "http://localhost:8080",
            None,
            "user@example.com",
            "pw",
            ensure_api_key=True,
            key_name="docs-mcp-server-automation",
            key_role="ADMIN",
            key_expiry_days=0,
        )
        assert token == "new"
        assert "Created API key" in capsys.readouterr().out

    def test_resolve_api_key_create_missing_token(self, monkeypatch):
        monkeypatch.setattr(signoz_provision, "create_session_token", lambda *_args, **_kwargs: "token")
        monkeypatch.setattr(signoz_provision, "list_api_keys", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(signoz_provision, "create_api_key", lambda *_args, **_kwargs: {})
        with pytest.raises(signoz_api.SignozError, match="did not return a token"):
            signoz_provision._resolve_api_key(
                "http://localhost:8080",
                None,
                "user@example.com",
                "pw",
                ensure_api_key=True,
                key_name="docs-mcp-server-automation",
                key_role="ADMIN",
                key_expiry_days=0,
            )

    def test_main_runs_scripts(self, monkeypatch):
        calls: list[list[str]] = []
        monkeypatch.setattr(signoz_provision, "_run_script", lambda args: calls.append(args))
        monkeypatch.setattr(signoz_provision, "_resolve_api_key", lambda *_args, **_kwargs: "key")
        monkeypatch.setattr(sys, "argv", ["signoz-provision", "--dry-run"])

        assert signoz_provision.main() == 0
        assert any("signoz-dashboards-sync.py" in call[0] for call in calls)
        assert any("signoz-alerts-sync.py" in call[0] for call in calls)
