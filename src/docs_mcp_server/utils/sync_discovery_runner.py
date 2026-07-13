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

from article_extractor import NetworkOptions
from article_extractor.discovery import CrawlConfig, EfficientCrawler
import httpx
from opentelemetry.trace import SpanKind

from docs_mcp_server.observability.tracing import create_span
from docs_mcp_server.utils.proxy_pool import (
    ProxyPool,
    is_usable_probe_response,
    proxy_label,
    should_rotate_proxy,
)
from docs_mcp_server.utils.url_normalization import canonicalize_markdown_mirror_url


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
        self._proxy_pool = ProxyPool(settings.get_proxy_list())

    def _canonicalize_discovered_url(self, url: str) -> str | None:
        return canonicalize_markdown_mirror_url(
            url,
            enabled=getattr(self.settings, "canonicalize_discovered_markdown_urls", False),
            markdown_url_suffix=getattr(self.settings, "markdown_url_suffix", ""),
            preserve_query_strings=getattr(self.settings, "preserve_query_strings", True),
            should_process_url=self.settings.should_process_url,
        )

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
            canonical_root_urls = {
                canonical for url in root_urls if (canonical := self._canonicalize_discovered_url(url)) is not None
            }

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
                canonical_url = self._canonicalize_discovered_url(url)
                if canonical_url is None:
                    return
                if canonical_url not in discovered_during_crawl and canonical_url not in canonical_root_urls:
                    discovered_during_crawl.add(canonical_url)
                    try:
                        asyncio.get_event_loop().call_soon_threadsafe(url_queue.put_nowait, canonical_url)
                    except Exception as e:
                        logger.warning("Failed to queue URL %s: %s", canonical_url, e)
                    try:
                        loop = asyncio.get_event_loop()
                        record_task = loop.create_task(
                            self.metadata_store.record_event(
                                url=canonical_url,
                                event_type="crawl_discovered",
                                status="ok",
                            )
                        )
                        track_task(record_task)
                        task = loop.create_task(
                            self.metadata_store.enqueue_urls({canonical_url}, reason="crawler_discovery", priority=0)
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

            def build_crawl_config(proxy: str | None) -> CrawlConfig:
                network = NetworkOptions(proxy=proxy) if proxy else None
                return CrawlConfig(
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
                    network=network,
                )

            async def run_crawler_once(proxy: str | None) -> tuple[set[str], int]:
                crawl_config = build_crawl_config(proxy)
                async with EfficientCrawler(root_urls, crawl_config) as crawler:
                    crawl = crawler.crawl()
                    if self._proxy_pool.has_proxies:
                        all_urls = await asyncio.wait_for(
                            crawl,
                            timeout=getattr(self.settings, "crawler_proxy_attempt_timeout_seconds", 45),
                        )
                    else:
                        all_urls = await crawl
                    crawler_skipped = crawler._crawler_skipped if hasattr(crawler, "_crawler_skipped") else 0
                    return set(all_urls), crawler_skipped

            async def record_success(all_urls: set[str], crawler_skipped: int, proxy: str | None) -> set[str]:
                if proxy:
                    self._proxy_pool.mark_success(proxy)
                canonical_urls = {
                    canonical for url in all_urls if (canonical := self._canonicalize_discovered_url(url)) is not None
                }
                discovered = canonical_urls - canonical_root_urls
                filtered_discovered = discovered

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
                        "proxy": proxy_label(proxy),
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
                        "proxy": proxy_label(proxy),
                    },
                )
                return filtered_discovered

            async def crawl_with_proxy_rotation() -> set[str]:
                if not self._proxy_pool.has_proxies:
                    all_urls, crawler_skipped = await run_crawler_once(None)
                    return await record_success(all_urls, crawler_skipped, None)

                attempts = 0
                for proxy in self._proxy_pool.candidates():
                    if not await self._probe_proxy(proxy, root_urls):
                        continue
                    attempts += 1
                    try:
                        logger.info("Starting crawler attempt (proxy=%s)", proxy_label(proxy))
                        all_urls, crawler_skipped = await run_crawler_once(proxy)
                        return await record_success(all_urls, crawler_skipped, proxy)
                    except asyncio.TimeoutError:
                        self._proxy_pool.mark_blocked(proxy)
                        logger.warning(
                            "Crawler proxy attempt timed out after %ss (proxy=%s)",
                            getattr(self.settings, "crawler_proxy_attempt_timeout_seconds", 45),
                            proxy_label(proxy),
                        )
                        await self.metadata_store.record_event(
                            url=None,
                            event_type="crawl_proxy_failed",
                            status="failed",
                            reason="TimeoutError",
                            detail={"proxy": proxy_label(proxy)},
                        )
                    except Exception as exc:
                        self._proxy_pool.mark_blocked(proxy)
                        logger.warning(
                            "Crawler proxy attempt failed (proxy=%s): %s",
                            proxy_label(proxy),
                            exc,
                            exc_info=True,
                        )
                        await self.metadata_store.record_event(
                            url=None,
                            event_type="crawl_proxy_failed",
                            status="failed",
                            reason=exc.__class__.__name__,
                            detail={"proxy": proxy_label(proxy)},
                        )

                reason = "all_proxy_attempts_failed" if attempts else "no_working_proxy"
                logger.warning("Skipping link discovery because %s", reason)
                await self.metadata_store.record_event(
                    url=None,
                    event_type="crawl_skipped",
                    status="skipped",
                    reason=reason,
                )
                return set()

            try:
                processor_task = asyncio.create_task(progressive_processor())
                span.add_event("sync.discovery.crawl.start", {"root_url_count": len(root_urls)})
                return await crawl_with_proxy_rotation()

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

    async def _probe_proxy(self, proxy: str, root_urls: set[str]) -> bool:
        """Validate one proxy against a deterministic root URL."""
        if not root_urls:
            return False
        probe_url = sorted(root_urls)[0]
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0),
                proxy=proxy,
            ) as client:
                resp = await client.get(probe_url, follow_redirects=True)
                if is_usable_probe_response(resp.status_code, resp.content):
                    logger.info("Crawler proxy probe OK (proxy=%s, status=%s)", proxy_label(proxy), resp.status_code)
                    self._proxy_pool.mark_success(proxy)
                    return True
                if should_rotate_proxy(resp.status_code, resp.content):
                    logger.warning(
                        "Crawler proxy probe blocked (proxy=%s, status=%s)",
                        proxy_label(proxy),
                        resp.status_code,
                    )
                    self._proxy_pool.mark_blocked(proxy)
        except Exception as exc:
            logger.debug("Crawler proxy probe failed (proxy=%s): %s", proxy_label(proxy), exc)
            self._proxy_pool.mark_blocked(proxy)
        return False

    async def _probe_working_proxy(self, root_urls: set[str]) -> str | None:
        """Try each proxy with a lightweight HTTP GET, return first that works."""
        if not self._proxy_pool.has_proxies or not root_urls:
            return None

        for proxy in self._proxy_pool.candidates():
            if await self._probe_proxy(proxy, root_urls):
                return proxy
        logger.info("All crawler proxies failed probe")
        return None
