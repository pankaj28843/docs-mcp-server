# How-To: Create Demo Artifacts (Showboat / Rodney)

**Goal**: Produce a reproducible Markdown artifact that proves what you ran locally (commands + captured output).

This is useful for AI agent work: it reduces "it works on my machine" ambiguity by attaching evidence.

## Prerequisites

- Dev dependencies installed: `uv sync --extra dev`
- Optional (for screenshots): a Chrome/Chromium install that Rodney can launch

## Install Tools

Install Showboat and Rodney as `uv` tools:

```bash
uv tool install showboat
uv tool install rodney
```

**Actual output from 2026-02-11 (versions):**

```text
$ showboat --version
0.4.0
$ rodney --version
0.3.0
```

## Generate A Proof Document

This repo includes a sample Showboat document:

- `demos/local-proof.md`

To create a new proof run (recommended: timestamp the filename so you never overwrite artifacts):

```bash
showboat init demos/local-proof-$(date +%F).md "docs-mcp-server: Local Proof"
showboat note demos/local-proof-$(date +%F).md "Capturing validation loop output and an offline search smoke test."
showboat exec demos/local-proof-$(date +%F).md bash "uv run ruff format . && uv run ruff check --fix ."
showboat exec demos/local-proof-$(date +%F).md bash "timeout 120 uv run pytest -m unit --cov=src/docs_mcp_server --cov-fail-under=95 -q"
showboat exec demos/local-proof-$(date +%F).md bash "timeout 120 uv run python integration_tests/ci_mcp_test.py"
showboat exec demos/local-proof-$(date +%F).md bash "uv run mkdocs build --strict"
```

## Offline Search Smoke Test (No Docker)

If you have existing cached docs in `mcp-data/`, you can run an offline search test using the example config:

```bash
timeout 120 uv run python debug_multi_tenant.py --config deployment.example.json --tenant drf --test search --query serializers
```

**Actual output from 2026-02-11 (excerpt):**

```text
🔒 Running in OFFLINE mode
🎯 Filtered to 1 tenant(s) from 10 total
🚀 Starting multi-tenant server...
✅ Server ready at http://127.0.0.1:33495
--- Testing tenant: drf ---
   ✅ Search successful, returned 5 results
```

## Screenshots (Optional, Rodney)

If you have a local web UI you want to capture (for example, docs preview via `mkdocs serve`), Rodney can take screenshots:

```bash
rodney start
rodney open http://localhost:8000/docs-mcp-server/
rodney screenshot demos/docs-home.png
rodney stop
```

!!! note "First run downloads Chromium"
    On first use, Rodney may download a pinned Chromium build into `~/.cache/rod/`.

    **Actual output from 2026-02-11 (excerpt):**

    ```text
    [launcher.Browser]... Download: https://storage.googleapis.com/chromium-browser-snapshots/...
    [launcher.Browser]... Downloaded: /home/pankaj/.cache/rod/browser/chromium-1321438
    Chrome started (PID ...)
    ```

## Verification

You can re-run and diff a proof doc:

```bash
showboat verify demos/local-proof.md
```

If outputs legitimately change (timings, dependency versions, etc.), use:

```bash
showboat verify demos/local-proof.md --output demos/local-proof.updated.md
```

## Related

- `README.md` (Quick Start + validation loop)
- `docs/contributing.md` (validation expectations)
- `docs/how-to/preview-docs-locally.md` (MkDocs live reload)
