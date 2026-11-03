"""Check TP Playbook documentation retrieval against official page evidence."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlparse


CASES = Path(__file__).with_name("tp_playbook_cases.json")


class CLIClient:
    def __init__(self, executable: str):
        self.executable = executable

    def call(self, *args):
        result = subprocess.run(
            [self.executable, *args, "--json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"exit {result.returncode}")
        return json.loads(result.stdout)

    def describe(self, tenant):
        return self.call("describe", tenant)

    def search(self, tenant, query):
        return self.call("search", tenant, query, "--size", "20")

    def fetch(self, tenant, url):
        return self.call("fetch", tenant, url)


def source_version(provenance, pattern):
    indexed = provenance.get("indexed_source") or {}
    if indexed.get("version_kind") == "versioned":
        return indexed.get("version")
    if not pattern:
        return None
    versions = {
        match.group(1)
        for prefix in provenance.get("canonical_url_prefixes", [])
        if (match := re.search(pattern, prefix))
    }
    return next(iter(versions)) if len(versions) == 1 else None


def page_match(url, page):
    parsed = urlparse(url)
    if parsed.scheme == "file":
        suffix = page.get("file_suffix")
        return bool(suffix and parsed.path.endswith("/" + suffix))
    path = page.get("path")
    return bool(parsed.scheme == "https" and path and parsed.path.rstrip("/") == path.rstrip("/"))


def git_revision_matches(case, provenance):
    return (
        provenance.get("source_type") == "git"
        and bool(case.get("expected_revision"))
        and provenance.get("source_revision") == case["expected_revision"]
    )


def source_evidence(case, provenance, url):
    if urlparse(url).scheme == "file":
        if case.get("expected_revision"):
            return "git_revision" if git_revision_matches(case, provenance) else None
        if (provenance.get("indexed_source") or {}).get("canonical_url") == case["source"]:
            return "indexed_source"
        return None
    return "url" if case["source"] and url.startswith(case["source"]) else None


def evaluate(case, client):  # noqa: PLR0911, PLR0912 - each failed evidence check exits immediately
    result = {
        "id": case["id"],
        "technology": case["technology"],
        "expected_source": case["source"],
        "project_version": case["project_version"],
        "expected_finding": case.get("expect", "retrieved"),
        "finding": None,
        "retrieval_pass": False,
        "pages": [],
    }
    try:
        info = client.describe(case["tenant"])
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        result["finding"] = "missing_tenant"
        result["failure"] = str(error)
        return result

    provenance = info.get("provenance") or {}
    result["actual_document_count"] = info.get("doc_count", 0)
    indexed = provenance.get("indexed_source") or {}
    result["actual_source"] = provenance.get("canonical_url_prefixes", []) or [indexed.get("canonical_url")]
    result["actual_source"] = [source for source in result["actual_source"] if source]
    result["freshness"] = provenance.get("freshness", {"state": "unknown"})
    result["index_id"] = provenance.get("index_id")
    result["source_revision"] = provenance.get("source_revision")
    result["source_version"] = source_version(provenance, case.get("version_pattern"))
    if git_revision_matches(case, provenance):
        result["source_version"] = case.get("source_version", case["project_version"])
    result["version_state"] = (
        "unknown"
        if not result["source_version"]
        else "match"
        if result["source_version"] == case["project_version"]
        else "mismatch"
    )

    if info.get("doc_count", 0) == 0:
        result["finding"] = "empty"
        return result
    if case.get("expect") == "empty":
        result["finding"] = "unexpected_documents"
        return result
    if case.get("expect") == "unknown_freshness":
        result["finding"] = (
            "unknown_freshness" if result["freshness"].get("state") == "unknown" else "freshness_now_known"
        )
        return result

    for page in case["pages"]:
        checked = {"query": page["query"], "expected_path": page.get("path") or page.get("file_suffix")}
        result["pages"].append(checked)
        try:
            hits = client.search(case["tenant"], page["query"]).get("results") or []
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            result["finding"] = "search_failed"
            checked["failure"] = str(error)
            return result
        checked["top_hits"] = [hit.get("url") for hit in hits[:5]]
        hit = next((item for item in hits if page_match(item.get("url", ""), page)), None)
        if hit is None:
            result["finding"] = "wrong_page"
            return result
        checked["rank"] = hits.index(hit) + 1
        checked["actual_url"] = hit["url"]
        evidence = source_evidence(case, provenance, hit["url"])
        if not evidence:
            result["finding"] = "wrong_source"
            return result
        checked["source_evidence"] = evidence
        try:
            fetched = client.fetch(case["tenant"], hit["url"])
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            result["finding"] = "fetch_failed"
            checked["failure"] = str(error)
            return result
        body = fetched.get("content") or ""
        checked["fetched_url"] = fetched.get("url")
        checked["truncated"] = fetched.get("truncated", False)
        checked["content_chars"] = len(body)
        checked["missing_terms"] = [term for term in page["terms"] if term.casefold() not in body.casefold()]
        if fetched.get("url") != hit["url"] or not body or checked["truncated"]:
            result["finding"] = "unfetchable_content"
            return result
        if checked["missing_terms"]:
            result["finding"] = "content_mismatch"
            return result
        if case.get("content_version_pattern"):
            match = re.search(case["content_version_pattern"], body, re.MULTILINE)
            checked["content_source_version"] = match.group(1) if match else None
            if not match or f"{case.get('content_url_prefix', 'url: ')}{hit['url']}" not in body:
                result["finding"] = "source_unverified"
                return result
            result["source_version"] = match.group(1)
            result["version_state"] = "match" if match.group(1) == case["project_version"] else "mismatch"
        page_version = source_version({"canonical_url_prefixes": [hit["url"]]}, case.get("version_pattern"))
        if page_version:
            checked["source_version"] = page_version
            result["source_version"] = page_version
            result["version_state"] = "match" if page_version == case["project_version"] else "mismatch"
            if result["version_state"] == "mismatch":
                result["finding"] = "version_mismatch"
                return result

    if result["version_state"] == "mismatch":
        result["finding"] = "version_mismatch"
    else:
        result["finding"] = "retrieved"
        result["retrieval_pass"] = True
    return result


def run(cases, client, live=False):
    results = []
    for case in cases:
        if live and case.get("fixture_only"):
            continue
        results.append(evaluate(case, client))
    return {
        "results": results,
        "summary": {
            "retrieval_passed": sum(result["retrieval_pass"] for result in results),
            "retrieval_required": sum(
                bool(case["pages"])
                for case in cases
                if not (live and case.get("fixture_only")) and case.get("expect") != "version_mismatch"
            ),
            "diagnostics_met": sum(
                result["finding"] == result["expected_finding"]
                for result in results
                if result["expected_finding"] != "retrieved"
            ),
            "diagnostics_required": sum(result["expected_finding"] != "retrieved" for result in results),
        },
    }


def quality_passed(report):
    summary = report["summary"]
    return (
        summary["retrieval_passed"] == summary["retrieval_required"]
        and summary["diagnostics_met"] == summary["diagnostics_required"]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="query the installed docsearch CLI")
    parser.add_argument("--docsearch", default="docsearch", help="docsearch executable")
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--output", type=Path, help="write the JSON report to this path")
    args = parser.parse_args()
    if not args.live:
        parser.error("pass --live to query documentation; fixtures run through pytest")
    report = run(json.loads(args.cases.read_text()), CLIClient(args.docsearch), live=True)
    content = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(content)
    else:
        sys.stdout.write(content)
    if not quality_passed(report):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
