# How-To: Preview Docs Locally

**Goal**: Preview the MkDocs site with live reload before you commit doc changes.
**Prerequisites**: Dev dependencies installed (see [Contributing](../contributing.md)), port 8000 free.

Use this workflow to verify formatting, navigation, and contrast before you push docs updates.

## Steps

1. **Start the dev server** from the repo root:

   ```bash
   uv run mkdocs serve --dev-addr localhost:8000
   ```

   **Actual output from 2026-01-14T14:24:19Z:**
   ```text
   INFO    -  Building documentation...
   INFO    -  Cleaning site directory
   INFO    -  Documentation built in 1.06 seconds
   INFO    -  [15:24:26] Serving on http://localhost:8000/docs-mcp-server/
   ```

2. **Open the site** in your browser:
   `http://localhost:8000/docs-mcp-server/`

3. **Edit a doc** (for example, `docs/index.md`) and confirm the page reloads.

## Verification

You should see the docs home page and the navigation update when you edit files.

## Troubleshooting

**Symptom**: `OSError: [Errno 98] Address already in use`

**Fix**: Stop the running server or use a different port (for example, `--dev-addr 127.0.0.1:8001`).

**Actual output from 2026-01-14T14:19:23Z (stack trace omitted; exit code printed at end):**
```text
INFO    -  Documentation built in 1.02 seconds
OSError: [Errno 98] Address already in use
1
```

## Related

- [Contributing](../contributing.md)
- [Documentation Standards](../contributing.md#documentation-standards)
