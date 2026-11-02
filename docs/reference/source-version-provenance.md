# Source version provenance

A tenant can declare curated `indexed_source` evidence in `deployment.json`:

```json
{
  "canonical_url": "https://docs.djangoproject.com/en/5.2/",
  "version_kind": "versioned",
  "version": "5.2",
  "evidence_url": "https://docs.djangoproject.com/en/5.2/"
}
```

Place this object inside the tenant configuration. The example illustrates the
schema; it does not assert that a particular deployment indexes Django 5.2.
Django's [5.2 documentation](https://docs.djangoproject.com/en/5.2/releases/)
identifies its release series, whereas Python's [3.12 documentation](https://docs.python.org/3.12/)
identifies a particular documentation release. Source-specific evidence and
comparison rules are necessary; a URL or a version string alone does not
establish compatibility with a project's installed package.

`canonical_url` identifies the official source. `version_kind` is one of:

- `versioned`: a single source version or series, specified in `version`.
- `unversioned`: the source has no applicable version designation.
- `current`: the source follows a moving current release; it does not establish
  the version of every page or compatibility with an installed release.
- `unknown`: the source's version scope is not established.

Use `null` or omit `version` for all kinds except `versioned`. An official
`evidence_url` is required for the first three kinds and optional for `unknown`.
Both URLs must be HTTP(S), with a host and without credentials or whitespace.
Curators must verify that the evidence supports the stated scope and that the
indexed corpus is restricted to that scope; schema validation cannot prove these
claims. Do not apply one version claim to mixed-version documents. Use separate
tenants or leave the version unknown until per-document evidence is available.

A successful index build snapshots this descriptor into
`manifest.json` under `provenance.indexed_source`. It participates in the
segment fingerprint, so changing the descriptor requires a new generation even
if the indexed documents are unchanged. A configuration change alone does not
modify an existing manifest. Existing manifests without a descriptor have
unknown source version evidence; no claim is inferred from configured URL
prefixes. The descriptor travels with the segment manifest during index data
export and import.

Source version and freshness answer different questions. Existing freshness
fields describe available indexed-document timestamp evidence or git sync
evidence; index creation time is not a source sync time. A known timestamp
does not prove the upstream crawl was complete or that all content is current.
Similarly, this descriptor records a curated claim at build time, not a
per-document verification or a guarantee of search quality.
