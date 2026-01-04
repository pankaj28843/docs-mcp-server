"""Tenant registry powering the single root MCP server."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse


if TYPE_CHECKING:
    from docs_mcp_server.deployment_config import TenantConfig
    from docs_mcp_server.tenant import TenantApp


@dataclass(frozen=True)
class TenantMetadata:
    """Curated metadata for a tenant, suitable for LLM consumption.

    This is a simplified view of TenantConfig that exposes only the
    information relevant for tool discovery and routing.
    """

    codename: str
    """Unique identifier for the tenant (e.g., 'django', 'fastapi')."""

    display_name: str
    """Human-readable name (e.g., 'Django REST Framework')."""

    description: str
    """Brief description of what documentation this tenant provides."""

    source_type: str
    """Type of documentation source: 'online', 'filesystem', or 'git'."""

    test_queries: list[str] = field(default_factory=list)
    """Example queries that work well with this tenant's documentation."""

    url_prefixes: list[str] = field(default_factory=list)
    """URL prefixes that this tenant handles (for online sources)."""

    supports_browse: bool = False
    """Whether the tenant exposes browse tools (filesystem/git)."""

    @classmethod
    def from_config(cls, config: "TenantConfig", tenant_app: "TenantApp") -> "TenantMetadata":
        """Create TenantMetadata from TenantConfig and TenantApp.

        Args:
            config: The tenant's configuration from deployment.json
            tenant_app: The instantiated TenantApp instance

        Returns:
            TenantMetadata with curated fields for LLM consumption
        """
        # Build description from docs_name, source type, and host/path hints
        source_descriptor = {
            "online": "Official",
            "filesystem": "Local",
            "git": "Git-synced",
        }.get(config.source_type, "Official")

        candidate_urls: list[str] = []
        if config.url_whitelist_prefixes:
            candidate_urls.extend(
                [value.strip() for value in config.url_whitelist_prefixes.split(",") if value.strip()]
            )
        if config.docs_entry_url:
            candidate_urls.extend([value.strip() for value in config.docs_entry_url if value.strip()])
        if config.docs_sitemap_url:
            candidate_urls.extend([value.strip() for value in config.docs_sitemap_url if value.strip()])

        hostnames: list[str] = []
        sections: list[str] = []
        for raw_url in candidate_urls:
            normalized_url = raw_url if "://" in raw_url else f"https://{raw_url}"
            try:
                parsed = urlparse(normalized_url)
            except ValueError:
                continue

            host = parsed.netloc or (parsed.path.split("/")[0] if parsed.path else "")
            if host and host not in hostnames:
                hostnames.append(host)

            path_segments = [segment for segment in parsed.path.split("/") if segment]
            filtered_segments = [
                segment
                for segment in path_segments
                if segment.lower() not in {"latest", "stable", "en"} and any(ch.isalpha() for ch in segment)
            ]
            if filtered_segments:
                label = filtered_segments[-1].replace("-", " ")
                if label not in sections:
                    sections.append(label)

        description_parts = [f"{source_descriptor} {config.docs_name} docs"]
        if sections:
            section_preview = ", ".join(sections[:3])
            if len(sections) > 3:
                section_preview = f"{section_preview}, ..."
            description_parts.append(f"covering {section_preview}")

        host_preview = ", ".join(hostnames[:2])
        if len(hostnames) > 2:
            host_preview = f"{host_preview}, ..."

        description = " ".join(description_parts)
        if host_preview:
            description = f"{description} ({host_preview})"

        # Flatten test_queries dict into a single list of example queries
        # test_queries is dict[str, list[str]] | None with keys like "natural", "phrases", "words"
        example_queries: list[str] = []
        if config.test_queries:
            for query_list in config.test_queries.values():
                example_queries.extend(query_list)

        # Convert comma-separated url_whitelist_prefixes string to list
        url_prefix_list: list[str] = []
        if config.url_whitelist_prefixes:
            url_prefix_list = [p.strip() for p in config.url_whitelist_prefixes.split(",") if p.strip()]

        return cls(
            codename=config.codename,
            display_name=config.docs_name,
            description=description,
            source_type=config.source_type,
            test_queries=example_queries,
            url_prefixes=url_prefix_list,
            supports_browse=tenant_app.supports_browse(),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for the root hub."""
        return {
            "codename": self.codename,
            "display_name": self.display_name,
            "description": self.description,
            "source_type": self.source_type,
            "test_queries": self.test_queries,
            "url_prefixes": self.url_prefixes,
            "supports_browse": self.supports_browse,
        }


class TenantRegistry:
    """Central registry of all tenant applications.

    Provides lookup methods for tenant metadata and app instances,
    used by the RootHub aggregator to implement proxy tools.

    Usage:
        # In app.py after creating tenant_apps_map
        registry = TenantRegistry()
        for codename, tenant_app in tenant_apps_map.items():
            registry.register(tenant_configs[codename], tenant_app)

        # In RootHub
        tenant = registry.get_tenant("django")
        all_tenants = registry.list_tenants()
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._tenants: dict[str, TenantApp] = {}
        self._configs: dict[str, TenantConfig] = {}
        self._metadata_cache: dict[str, TenantMetadata] = {}

    def register(self, config: "TenantConfig", tenant_app: "TenantApp") -> None:
        """Register a tenant application.

        Args:
            config: The tenant's configuration from deployment.json
            tenant_app: The instantiated TenantApp instance
        """
        codename = config.codename
        self._tenants[codename] = tenant_app
        self._configs[codename] = config
        # Clear cached metadata (will be regenerated on next access)
        self._metadata_cache.pop(codename, None)

    def get_tenant(self, codename: str) -> "TenantApp | None":
        """Get tenant application by codename.

        Args:
            codename: Unique tenant identifier

        Returns:
            TenantApp instance or None if not found
        """
        return self._tenants.get(codename)

    def get_metadata(self, codename: str) -> TenantMetadata | None:
        """Get curated tenant metadata by codename.

        Args:
            codename: Unique tenant identifier

        Returns:
            TenantMetadata or None if not found
        """
        if codename not in self._tenants:
            return None

        # Use cached metadata if available
        if codename not in self._metadata_cache:
            config = self._configs[codename]
            tenant_app = self._tenants[codename]
            self._metadata_cache[codename] = TenantMetadata.from_config(config, tenant_app)

        return self._metadata_cache[codename]

    def list_tenants(self) -> list[TenantMetadata]:
        """List all registered tenants with their metadata.

        Returns:
            List of TenantMetadata for all registered tenants
        """
        result: list[TenantMetadata] = []
        for codename in self._tenants:
            metadata = self.get_metadata(codename)
            if metadata is not None:
                result.append(metadata)
        return result

    def list_codenames(self) -> list[str]:
        """List all registered tenant codenames.

        Returns:
            List of codename strings
        """
        return list(self._tenants.keys())

    def is_filesystem_tenant(self, codename: str) -> bool:
        """Check if a tenant uses filesystem storage.

        Args:
            codename: Unique tenant identifier

        Returns:
            True if tenant uses filesystem or git source, False otherwise
        """
        config = self._configs.get(codename)
        if config is None:
            return False
        return config.source_type in ("filesystem", "git")

    def __len__(self) -> int:
        """Return number of registered tenants."""
        return len(self._tenants)

    def __contains__(self, codename: str) -> bool:
        """Check if codename is registered."""
        return codename in self._tenants
