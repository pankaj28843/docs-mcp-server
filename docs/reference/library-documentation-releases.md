# Library documentation releases

The documentation tenant audit on 2026-10-29 selected these stable sources.
These are documentation corpus versions; they do not change the server's Python dependencies.

| Tenant | Stable documentation source |
|---|---|
| `django` | [Django 6.1](https://docs.djangoproject.com/en/6.1/), corresponding to the [6.1.2 release](https://www.djangoproject.com/download/) |
| `python` | [Python 3.15](https://docs.python.org/3.15/) |
| `pytorch` | [PyTorch 2.14](https://docs.pytorch.org/docs/2.14/index.html), selected by the upstream stable redirect |
| `sqlalchemy` | [SQLAlchemy 2.1](https://docs.sqlalchemy.org/en/21/), selected by the upstream stable redirect |
| `flask` | [Flask stable](https://flask.palletsprojects.com/en/stable/) |
| `django-extensions` | [Django Extensions stable](https://django-extensions.readthedocs.io/en/stable/) |
| `chromadb` | [Git release `1.5.9`](https://github.com/chroma-core/chroma/releases/tag/1.5.9) |
| `crux-source` | [Git release `crux_core-v0.20.0`](https://github.com/redbadger/crux/releases/tag/crux_core-v0.20.0) |
| `deepeval` | [Git release `python-v4.2.4`](https://github.com/confident-ai/deepeval/releases/tag/python-v4.2.4) |
| `mkdocs` | [Git release `1.6.1`](https://github.com/mkdocs/mkdocs/releases/tag/1.6.1) |
| `openclaw` | [Git release `v2026.10.8`](https://github.com/openclaw/openclaw/releases/tag/v2026.10.8) |
| `opensearch-py` | [Git release `v3.2.0`](https://github.com/opensearch-project/opensearch-py/releases/tag/v3.2.0) |
| `sentence-transformers` | [Git release `v6.2.0`](https://github.com/huggingface/sentence-transformers/releases/tag/v6.2.0) |
| `terraform-aws-provider` | [Git release `v6.71.0`](https://github.com/hashicorp/terraform-provider-aws/releases/tag/v6.71.0) |
| `textual` | [Git release `v8.2.8`](https://github.com/Textualize/textual/releases/tag/v8.2.8) |

Git versions come from each repository's `releases/latest` API response, which
excludes draft and prerelease releases. Tenants for documentation-only repositories
continue tracking their configured branches. Other online library tenants already
use rolling upstream documentation URLs.

`deployment.json` is the local deployment source; `deployment.docker.json` is its
generated container configuration. Both are untracked deployment files. The
tracked `deployment.example.json` demonstrates the Django, Python, and MkDocs
versions above.

Python's root sitemap lists version homepages. Python, PyTorch, SQLAlchemy, Flask, and
Django Extensions use their versioned Sphinx `objects.inv` inventories in
`docs_sitemap_url`. The fetcher reads `std:doc` entries, resolves their URLs,
deduplicates pages, and applies the tenant URL filters. See the
[Sphinx inventory documentation](https://www.sphinx-doc.org/en/master/usage/extensions/intersphinx.html).
These tenants disable rendered link discovery and fetch the enumerated pages
directly.

The six online tenants above use `article_proxies: ""` in the local configuration
after a container probe showed direct access working while the configured proxy
failed. Other tenants retain their proxy configuration.

For Git tenant settings, see [Configure a Git tenant](../how-to/configure-git-tenant.md).
For operational endpoints, see the [deployment schema](deployment-json-schema.md).
