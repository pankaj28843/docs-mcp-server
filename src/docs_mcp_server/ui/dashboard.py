"""HTML dashboard renderer."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


@lru_cache(maxsize=1)
def _get_env() -> Environment:
    """Construct and cache the Jinja environment lazily."""
    if not _TEMPLATE_DIR.is_dir():
        raise RuntimeError(f"Dashboard templates directory not found: {_TEMPLATE_DIR}")
    return Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )


def render_dashboard_html(tenant_codenames: list[str]) -> str:
    template = _get_env().get_template("dashboard.html")
    return template.render(tenant_codenames=sorted(tenant_codenames))


def render_tenant_dashboard_html(tenant_codename: str) -> str:
    template = _get_env().get_template("dashboard_tenant.html")
    return template.render(tenant_codename=tenant_codename)
