"""Deep helper for sync discovery orchestration.

Encapsulates complex crawling logic behind simple interface:
- Lock management
- Progressive URL processing
- Crawler configuration
- Stats tracking
"""

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import TYPE_CHECKING

from article_extractor.discovery import CrawlConfig, EfficientCrawler


if TYPE_CHECKING:
    from docs_mcp_server.models import SyncStats, TenantSettings
    from docs_mcp_server.utils.sync_metadata_store import SyncMetadataStore

logger = logging.getLogger(__name__)


class SyncDiscoveryRunner:
    """Deep module for running sync discovery with minimal interface.

    Hides complexity:
    - Crawler lock management
    - Progressive URL processing
    - Recently-visited checks
    - Stats updates

    Simple interface: run(root_urls, force_crawl) -> discovered_urls
    """

    def __init__(
        self,
        tenant_codename: str,
        settings: "TenantSettings",
        metadata_store: "SyncMetadataStore",
        stats: "SyncStats",
        schedule_interval_hours: int,
        process_url_callback: Callable[[str, str | None], "asyncio.Future[None]"],
        acquire_crawler_lock_callback: Callable[[], "asyncio.Future[str | None]"],
    ):
        self.tenant_codename = tenant_codename
        self.settings = settings
        self.metadata_store = metadata_store
        self.stats = stats
        self.schedule_interval_hours = schedule_interval_hours
        self._process_url = process_url_callback
        self._acquire_crawler_lock = acquire_crawler_lock_callback

    async def run(self, root_urls: set[str], force_crawl: bool = False) -> set[str]:
        """Run discovery crawl from root URLs.

        Args:
            root_urls: Set of root URLs to crawl from
            force_crawl: If True, ignore idempotency and crawl all URLs

        Returns:
            Set of discovered URLs (filtered, excluding roots)
        """
        logger.info(f"Starting link discovery from {len(root_urls)} root URLs (force_crawl={force_crawl})")

        self.stats.discovery_root_urls = len(root_urls)
        self.stats.discovery_discovered = 0
        self.stats.discovery_filtered = 0
        self.stats.discovery_progressively_processed = 0

        lease = await self._acquire_crawler_lock()
        if not lease:
            logger.info("Skipping link discovery because crawler lock is unavailable (tenant=%s)", self.tenant_codename)
            return set()

        discovered_during_crawl: set[str] = set()
        url_queue: asyncio.Queue[str] = asyncio.Queue()

        async def progressive_processor():
            """Process URLs as they're discovered by the crawler."""
            processed = 0
            while True:
                try:
                    url = await asyncio.wait_for(url_queue.get(), timeout=1.0)
                    if url is None:  # Sentinel to stop
                        break
                    await self._process_url(url, None)
                    processed += 1
                    self.stats.discovery_progressively_processed = processed
                    if processed % 50 == 0:
                        logger.info(f"Progressive processing: {processed} URLs processed")
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.warning(f"Progressive processing error: {e}")

        processor_task: asyncio.Task | None = None

        def on_url_discovered(url: str):
            """Callback for progressive URL processing as crawler discovers them."""
            if url not in discovered_during_crawl and url not in root_urls:
                discovered_during_crawl.add(url)
                try:
                    asyncio.get_event_loop().call_soon_threadsafe(url_queue.put_nowait, url)
                except Exception as e:
                    logger.warning(f"Failed to queue URL {url}: {e}")

        def check_recently_visited(url: str) -> bool:
            """Check if URL was recently fetched (within schedule interval).

            Returns True if URL should be skipped (recently visited).
            """
            try:
                digest = hashlib.sha256(url.encode()).hexdigest()
                meta_path = self.metadata_store.metadata_root / f"url_{digest}.json"

                if not meta_path.exists():
                    return False

                data = json.loads(meta_path.read_text(encoding="utf-8"))
                last_fetched_str = data.get("last_fetched_at")
                last_status = data.get("last_status")

                if not last_fetched_str or last_status != "success":
                    return False

                last_fetched = datetime.fromisoformat(last_fetched_str)
                now = datetime.now(timezone.utc)
                age_hours = (now - last_fetched).total_seconds() / 3600

                return age_hours < self.schedule_interval_hours

            except Exception as e:
                logger.debug(f"Error checking recently visited for {url}: {e}")
                return False

        crawl_config = CrawlConfig(
            timeout=30,
            delay_seconds=0.3,
            max_pages=self.settings.max_crawl_pages,
            same_host_only=True,
            allow_querystrings=False,
            on_url_discovered=on_url_discovered,
            skip_recently_visited=check_recently_visited,
            force_crawl=force_crawl,
            markdown_url_suffix=self.settings.markdown_url_suffix or None,
            prefer_playwright=self.settings.crawler_playwright_first,
            user_agent_provider=self.settings.get_random_user_agent,
            should_process_url=self.settings.should_process_url,
            min_concurrency=self.settings.crawler_min_concurrency,
            max_concurrency=self.settings.crawler_max_concurrency,
            max_sessions=self.settings.crawler_max_sessions,
        )

        try:
            processor_task = asyncio.create_task(progressive_processor())

            async with EfficientCrawler(root_urls, crawl_config) as crawler:
                all_urls = await crawler.crawl()

                discovered = all_urls - root_urls
                filtered_discovered = {url for url in discovered if self.settings.should_process_url(url)}

                crawler_skipped = crawler._crawler_skipped if hasattr(crawler, "_crawler_skipped") else 0
                logger.info(
                    f"Crawl complete: {len(all_urls)} total URLs, "
                    f"{len(discovered)} discovered (excluding roots), "
                    f"{len(filtered_discovered)} after filtering, "
                    f"{len(discovered_during_crawl)} progressively queued, "
                    f"{crawler_skipped} skipped (recently visited)"
                )

                self.stats.last_crawler_run = datetime.now(timezone.utc).isoformat()
                self.stats.crawler_total_runs += 1
                self.stats.discovery_discovered = len(discovered)
                self.stats.discovery_filtered = len(filtered_discovered)
                self.stats.discovery_sample = sorted(filtered_discovered)[:10]

                return filtered_discovered

        except Exception as e:
            logger.error(f"Error during link crawling: {e}", exc_info=True)
            return set()
        finally:
            try:
                await url_queue.put(None)
            except Exception:
                pass
            if processor_task:
                try:
                    await processor_task
                except Exception:
                    processor_task.cancel()
            await self.metadata_store.release_lock(lease)
