import json
from pathlib import Path

import pytest

from scripts.quality.check_tp_playbook_retrieval import evaluate, run


ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "scripts/quality/tp_playbook_cases.json").read_text())
FIXTURE = json.loads((ROOT / "tests/fixtures/quality/retrieval_responses.json").read_text())


class FixtureClient:
    def __init__(self, fixture):
        self.fixture = fixture

    def describe(self, tenant):
        if tenant not in self.fixture["descriptions"]:
            raise RuntimeError("tenant not found")
        return self.fixture["descriptions"][tenant]

    def search(self, tenant, query):
        return {"results": self.fixture["searches"].get(tenant, [])}

    def fetch(self, tenant, url):
        return self.fixture["fetches"][url]


def case(case_id):
    return next(item for item in CASES if item["id"] == case_id)


@pytest.mark.unit
def test_case_catalog_covers_playbook_and_diagnostic_states():
    assert len(CASES) == 15
    assert {item["id"] for item in CASES} == {
        "DJ-CSRF",
        "DJ-HTML",
        "S3-PRIVATE",
        "API-SCHEMA",
        "ANG-ROUTE",
        "ANG-MATERIAL",
        "RXJS",
        "GO-CLI",
        "OTEL-GO",
        "OTEL-PY",
        "CADDY-SPA",
        "EMPTY",
        "UNKNOWN",
        "MATCH",
        "MISMATCH",
    }
    assert all(item["source"] or item["expect"] == "empty" for item in CASES)
    assert all(page["terms"] for item in CASES for page in item["pages"])


@pytest.mark.unit
def test_matching_version_requires_fetched_official_content():
    result = evaluate(case("MATCH"), FixtureClient(FIXTURE))
    assert result["finding"] == "retrieved"
    assert result["retrieval_pass"]
    assert result["version_state"] == "match"
    assert result["pages"][0]["rank"] == 1


@pytest.mark.unit
def test_wrong_version_is_reported_even_when_content_is_relevant():
    result = evaluate(case("MISMATCH"), FixtureClient(FIXTURE))
    assert result["finding"] == "version_mismatch"
    assert not result["retrieval_pass"]
    assert result["source_version"] == "6.1"
    assert result["pages"][0]["missing_terms"] == []


@pytest.mark.unit
def test_empty_and_unknown_freshness_are_distinct():
    client = FixtureClient(FIXTURE)
    assert evaluate(case("EMPTY"), client)["finding"] == "empty"
    unknown = evaluate(case("UNKNOWN"), client)
    assert unknown["finding"] == "unknown_freshness"
    assert unknown["freshness"]["state"] == "unknown"
    assert unknown["index_id"] is None


@pytest.mark.unit
def test_missing_tenant_is_visible_in_report():
    result = evaluate(case("ANG-ROUTE"), FixtureClient(FIXTURE))
    assert result["finding"] == "missing_tenant"
    assert not result["retrieval_pass"]
    assert "tenant not found" in result["failure"]


@pytest.mark.unit
def test_wrong_page_and_truncated_content_do_not_pass():
    fixture = json.loads(json.dumps(FIXTURE))
    fixture["searches"]["quality-django-52"] = [{"url": "https://docs.djangoproject.com/en/5.2/topics/security/"}]
    assert evaluate(case("MATCH"), FixtureClient(fixture))["finding"] == "wrong_page"
    fixture["searches"]["quality-django-52"] = FIXTURE["searches"]["quality-django-52"]
    fixture["fetches"]["https://docs.djangoproject.com/en/5.2/ref/csrf/"]["truncated"] = True
    assert evaluate(case("MATCH"), FixtureClient(fixture))["finding"] == "unfetchable_content"


@pytest.mark.unit
def test_report_keeps_coverage_failures_separate_from_diagnostics():
    report = run([case("MATCH"), case("MISMATCH"), case("EMPTY"), case("UNKNOWN")], FixtureClient(FIXTURE))
    assert report["summary"] == {
        "retrieval_passed": 1,
        "retrieval_required": 1,
        "diagnostics_met": 3,
        "diagnostics_required": 3,
    }
