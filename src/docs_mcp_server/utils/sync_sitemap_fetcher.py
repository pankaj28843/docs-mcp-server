"""Deep helper for sitemap fetching and parsing.

Encapsulates complex sitemap logic behind simple interface:
- HTTP client configuration
- XML parsing with lxml
- URL filtering
- Change detection via hashing
- Snapshot persistence
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
import hashlib
import logging
from typing import TYPE_CHECKING

import httpx
from lxml import etree  # type: ignore[import-untyped]

from ..utils.models import SitemapEntry


if TYPE_CHECKING:
    from docs_mcp_server.models import TenantSettings

logger = logging.getLogger(__name__)


class SyncSitemapFetcher:
    """Deep module for fetching and parsing sitemaps with minimal interface.

    Hides complexity:
    - HTTP client setup (headers, timeouts)
    - XML parsing (lxml)
    - URL filtering
    - Change detection (hashing)
    - Snapshot persistence

    Simple interface: fetch(sitemap_urls) -> (changed, entries)
    """

    def __init__(
        self,
        settings: "TenantSettings",
        get_snapshot_callback: Callable[[str], Awaitable[dict | None]],
        save_snapshot_callback: Callable[[dict, str | None], Awaitable[None]],
    ):
        self.settings = settings
        self._get_sitemap_snapshot = get_snapshot_callback
        self._save_sitemap_snapshot = save_snapshot_callback

    async def fetch(self, sitemap_urls: list[str]) -> tuple[bool, list[SitemapEntry]]:
        """Fetch sitemaps and check if any changed.

        Args:
            sitemap_urls: List of sitemap URLs to fetch

        Returns:
            Tuple of (any_changed, all_entries)
        """
        logger.info(f"Fetching {len(sitemap_urls)} sitemaps: {', '.join(sitemap_urls)}")

        all_entries = []
        any_changed = False
        total_sitemap_urls = 0
        total_filtered_count = 0

        timeout = httpx.Timeout(120.0, connect=30.0)
        headers = {
            "User-Agent": self.settings.get_random_user_agent(),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
        }

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            for sitemap_url in sitemap_urls:
                logger.info(f"Fetching sitemap: {sitemap_url}")

                try:
                    resp = await client.get(sitemap_url)
                    resp.raise_for_status()

                    if not resp.content:
                        logger.error(f"Empty response for sitemap {sitemap_url}")
                        continue

                    content_preview = resp.content[:200].decode("utf-8", errors="ignore")
                    logger.info(f"Sitemap response ({len(resp.content)} bytes) starts with: {content_preview[:100]}")

                    content_hash = hashlib.sha256(resp.content).hexdigest()

                    try:
                        root = etree.fromstring(resp.content)
                    except etree.XMLSyntaxError as xml_err:
                        logger.error(f"XML syntax error parsing sitemap {sitemap_url}: {xml_err}")
                        logger.error(f"Content preview: {content_preview}")
                        raise

                    sitemap_total_urls = len(root.findall("{*}url"))
                    total_sitemap_urls += sitemap_total_urls
                    entries = []

                    for url_elem in root.findall("{*}url"):
                        loc = url_elem.find("{*}loc").text

                        if not self.settings.should_process_url(loc):
                            continue

                        lastmod_elem = url_elem.find("{*}lastmod")
                        lastmod = None
                        if lastmod_elem is not None and lastmod_elem.text:
                            try:
                                lastmod = datetime.fromisoformat(lastmod_elem.text.replace("Z", "+00:00"))
                            except Exception:
                                pass
                        entries.append(SitemapEntry(url=loc, lastmod=lastmod))

                    filtered_count = sitemap_total_urls - len(entries)
                    total_filtered_count += filtered_count
                    all_entries.extend(entries)

                    sitemap_key = f"sitemap_{hashlib.sha256(sitemap_url.encode()).hexdigest()[:8]}"
                    previous_snapshot = await self._get_sitemap_snapshot(sitemap_key)
                    changed = True

                    if previous_snapshot:
                        previous_hash = previous_snapshot.get("content_hash")
                        changed = previous_hash != content_hash

                    if changed:
                        any_changed = True

                    await self._save_sitemap_snapshot(
                        {
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                            "entry_count": len(entries),
                            "total_urls": sitemap_total_urls,
                            "filtered_count": filtered_count,
                            "content_hash": content_hash,
                            "sitemap_url": sitemap_url,
                        },
                        sitemap_key,
                    )

                    status = "changed" if changed else "unchanged"
                    logger.info(
                        f"Sitemap {sitemap_url} {status}: {len(entries)} entries "
                        f"(filtered {filtered_count} from {sitemap_total_urls})"
                    )

                except etree.XMLSyntaxError as e:
                    logger.error(f"XML parsing error for sitemap {sitemap_url}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error fetching sitemap {sitemap_url}: {e}")
                    continue

        combined_hash = hashlib.sha256("|".join(sitemap_urls).encode()).hexdigest()
        await self._save_sitemap_snapshot(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "entry_count": len(all_entries),
                "total_urls": total_sitemap_urls,
                "filtered_count": total_filtered_count,
                "content_hash": combined_hash,
                "sitemap_count": len(sitemap_urls),
            }
        )

        logger.info(
            f"Combined sitemaps: {len(all_entries)} total entries "
            f"(filtered {total_filtered_count} from {total_sitemap_urls})"
        )
        return any_changed, all_entries
