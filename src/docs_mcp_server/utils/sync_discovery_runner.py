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
import logging
from typing import TYPE_CHECKING

from article_extractor.discovery import CrawlConfig, EfficientCrawler
from opentelemetry.trace import SpanKind

from docs_mcp_server.observability.tracing import create_span


if TYPE_CHECKING:
    from docs_mcp_server.models import SyncStats, TenantSettings
    from docs_mcp_server.utils.crawl_state_store import CrawlStateStore

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
        metadata_store: "CrawlStateStore",
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
        logger.info("Starting link discovery from %s root URLs (force_crawl=%s)", len(root_urls), force_crawl)

        self.stats.discovery_root_urls = len(root_urls)
        self.stats.discovery_discovered = 0
        self.stats.discovery_filtered = 0
        self.stats.discovery_progressively_processed = 0

        with create_span(
            "sync.discovery.run",
            kind=SpanKind.INTERNAL,
            attributes={
                "sync.tenant": self.tenant_codename,
                "sync.force_crawl": force_crawl,
                "sync.root_url_count": len(root_urls),
                "sync.schedule_interval_hours": self.schedule_interval_hours,
            },
        ) as span:
            await self.metadata_store.record_event(
                url=None,
                event_type="crawl_start",
                status="ok",
                detail={"root_url_count": len(root_urls), "force_crawl": force_crawl},
            )
            span.add_event("sync.discovery.lock.requested", {})
            lease = await self._acquire_crawler_lock()
            if not lease:
                logger.info(
                    "Skipping link discovery because crawler lock is unavailable (tenant=%s)",
                    self.tenant_codename,
                )
                span.add_event("sync.discovery.lock.unavailable", {})
                span.set_attribute("sync.lock_acquired", False)
                await self.metadata_store.record_event(
                    url=None,
                    event_type="crawl_skipped",
                    status="skipped",
                    reason="lock_unavailable",
                )
                return set()

            span.set_attribute("sync.lock_acquired", True)
            span.add_event("sync.discovery.lock.acquired", {})

            discovered_during_crawl: set[str] = set()
            url_queue: asyncio.Queue[str] = asyncio.Queue()
            enqueue_tasks: set[asyncio.Task] = set()

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
                            logger.info("Progressive processing: %s URLs processed", processed)
                            span.add_event("sync.discovery.progress", {"processed": processed})
                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        logger.warning("Progressive processing error: %s", e)
                        span.add_event("sync.discovery.progress.error", {"error.type": e.__class__.__name__})

            processor_task: asyncio.Task | None = None

            def track_task(task: asyncio.Task) -> None:
                enqueue_tasks.add(task)
                task.add_done_callback(lambda t: enqueue_tasks.discard(t))

            def on_url_discovered(url: str):
                """Callback for progressive URL processing as crawler discovers them."""
                if not self.settings.should_process_url(url):
                    return
                if url not in discovered_during_crawl and url not in root_urls:
                    discovered_during_crawl.add(url)
                    try:
                        asyncio.get_event_loop().call_soon_threadsafe(url_queue.put_nowait, url)
                    except Exception as e:
                        logger.warning("Failed to queue URL %s: %s", url, e)
                    try:
                        loop = asyncio.get_event_loop()
                        record_task = loop.create_task(
                            self.metadata_store.record_event(
                                url=url,
                                event_type="crawl_discovered",
                                status="ok",
                            )
                        )
                        track_task(record_task)
                        task = loop.create_task(
                            self.metadata_store.enqueue_urls({url}, reason="crawler_discovery", priority=0)
                        )
                        track_task(task)
                    except Exception as e:
                        logger.error("Failed to enqueue URL in crawl DB: %s", e, exc_info=True)

            def check_recently_visited(url: str) -> bool:
                """Check if URL was recently fetched (within schedule interval).

                Returns True if URL should be skipped (recently visited).
                """
                try:
                    return self.metadata_store.was_recently_fetched_sync(
                        url, interval_hours=self.schedule_interval_hours
                    )

                except Exception as e:
                    logger.debug("Error checking recently visited for %s: %s", url, e)
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
                span.add_event("sync.discovery.crawl.start", {"root_url_count": len(root_urls)})

                async with EfficientCrawler(root_urls, crawl_config) as crawler:
                    all_urls = await crawler.crawl()

                    discovered = all_urls - root_urls
                    filtered_discovered = {url for url in discovered if self.settings.should_process_url(url)}

                    crawler_skipped = crawler._crawler_skipped if hasattr(crawler, "_crawler_skipped") else 0
                    logger.info(
                        "Crawl complete: %s total URLs, %s discovered (excluding roots), "
                        "%s after filtering, %s progressively queued, %s skipped (recently visited)",
                        len(all_urls),
                        len(discovered),
                        len(filtered_discovered),
                        len(discovered_during_crawl),
                        crawler_skipped,
                    )

                    span.add_event(
                        "sync.discovery.crawl.complete",
                        {
                            "total_urls": len(all_urls),
                            "discovered": len(discovered),
                            "filtered": len(filtered_discovered),
                            "queued": len(discovered_during_crawl),
                            "skipped_recent": crawler_skipped,
                        },
                    )

                    self.stats.last_crawler_run = datetime.now(timezone.utc).isoformat()
                    self.stats.crawler_total_runs += 1
                    self.stats.discovery_discovered = len(discovered)
                    self.stats.discovery_filtered = len(filtered_discovered)
                    self.stats.discovery_sample = sorted(filtered_discovered)[:10]

                    await self.metadata_store.record_event(
                        url=None,
                        event_type="crawl_complete",
                        status="ok",
                        detail={
                            "total_urls": len(all_urls),
                            "discovered": len(discovered),
                            "filtered": len(filtered_discovered),
                            "queued": len(discovered_during_crawl),
                            "skipped_recent": crawler_skipped,
                        },
                    )
                    return filtered_discovered

            except Exception as e:
                logger.error("Error during link crawling: %s", e, exc_info=True)
                span.add_event("sync.discovery.error", {"error.type": e.__class__.__name__})
                span.set_attribute("error", True)
                await self.metadata_store.record_event(
                    url=None,
                    event_type="crawl_error",
                    status="failed",
                    reason=e.__class__.__name__,
                )
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
                if enqueue_tasks:
                    await asyncio.gather(*enqueue_tasks, return_exceptions=True)
                await self.metadata_store.release_lock(lease)
