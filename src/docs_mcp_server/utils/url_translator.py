"""URL translation service for mapping between file paths and canonical URLs."""

import hashlib
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


class UrlTranslator:
    """Bidirectional translator between file paths and canonical URLs."""

    def __init__(self, tenant_data_dir: Path):
        """Initialize the URL translator.

        Args:
            tenant_data_dir: The root directory for the tenant's data files.
        """
        # Normalize to an absolute path so metadata lookups work even when
        # deployment.json provided a relative docs_root_dir. This keeps the
        # translator aligned with repositories that resolve their base paths.
        self.tenant_data_dir = tenant_data_dir.expanduser().resolve(strict=False)

    def get_internal_path_from_public_url(self, public_url: str) -> Path:
        """
        Derive the internal file path from a public URL using a deterministic hash.

        This allows for a stateless reverse mapping from a public-facing URL
        to the internal file hash used for storage.

        Args:
            public_url: The canonical public URL of the document.

        Returns:
            The full path to the internal markdown file.
        """
        # The hash is based on the URL without any fragments or our custom query params
        # to ensure canonical representation.
        parsed_url = urlparse(public_url)
        query_params = parse_qs(parsed_url.query)
        query_params.pop("rg", None)  # Remove our specific metadata param

        # Rebuild query string, ensuring keys are sorted for deterministic output.
        # This is critical for ensuring the hash is the same regardless of original param order.
        sorted_query_items = sorted((k, v) for k, values in query_params.items() for v in values)
        new_query = urlencode(sorted_query_items)

        # Normalize path to ensure consistency for URLs with and without trailing slashes
        # that point to the same resource (e.g., directory indexes).
        normalized_path = parsed_url.path
        # Check if path has a file extension (e.g., .html, .pdf) by looking at the last component
        # Don't use Path().suffix as it's meant for filesystem paths, not URL paths
        has_file_extension = "." in normalized_path.rstrip("/").split("/")[-1] if normalized_path else False
        if not has_file_extension and not normalized_path.endswith("/"):
            normalized_path += "/"

        canonical_url = urlunparse(
            (
                parsed_url.scheme,
                parsed_url.netloc,
                normalized_path,
                parsed_url.params,
                new_query,
                "",  # Always strip fragment for canonical URL
            )
        )

        url_hash = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
        return self.tenant_data_dir / f"{url_hash}.md"
