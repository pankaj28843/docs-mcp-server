"""HTML dashboard renderer."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_dashboard_html(tenant_codenames: list[str]) -> str:
    template = _ENV.get_template("dashboard.html")
    return template.render(tenant_codenames=sorted(tenant_codenames))


def render_tenant_dashboard_html(tenant_codename: str) -> str:
    template = _ENV.get_template("dashboard_tenant.html")
    return template.render(tenant_codename=tenant_codename)
