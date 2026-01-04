"""Efficient BFS-based web crawler for documentation sites.

This module implements a pragmatic, patient crawler with just enough features
to support the docs MCP server. It uses sets for efficient URL tracking,
implements proper rate limiting, and honors URL filters.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import time
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
import httpx

from ..config import Settings


logger = logging.getLogger(__name__)


@dataclass
class RateLimitEvent:
    """Tracks a rate limit event for adaptive backoff."""

    timestamp: float
    host: str
    status_code: int
    was_success: bool


@dataclass
class HostRateLimitState:
    """Tracks rate limiting state for a specific host."""

    host: str
    base_delay: float = 2.0  # Starting delay
    current_delay: float = 2.0  # Adaptive delay
    min_delay: float = 0.5  # Floor
    max_delay: float = 120.0  # Ceiling (2 minutes)
    consecutive_429s: int = 0
    consecutive_successes: int = 0
    total_429s: int = 0
    total_requests: int = 0
    last_429_time: float = 0.0
    events: deque = field(default_factory=lambda: deque(maxlen=100))

    def record_success(self):
        """Record a successful request - gradually reduce delay."""
        self.consecutive_429s = 0
        self.consecutive_successes += 1
        self.total_requests += 1
        self.events.append(
            RateLimitEvent(
                timestamp=time.time(),
                host=self.host,
                status_code=200,
                was_success=True,
            )
        )

        # Gradually reduce delay after sustained success
        # Require 10 consecutive successes before reducing
        if self.consecutive_successes >= 10:
            reduction = 0.9  # Reduce by 10%
            self.current_delay = max(self.min_delay, self.current_delay * reduction)
            self.consecutive_successes = 0
            logger.debug(f"[{self.host}] Reduced delay to {self.current_delay:.2f}s after successful streak")

    def record_429(self):
        """Record a 429 response - increase delay significantly."""
        now = time.time()
        self.consecutive_successes = 0
        self.consecutive_429s += 1
        self.total_429s += 1
        self.total_requests += 1
        self.events.append(
            RateLimitEvent(
                timestamp=now,
                host=self.host,
                status_code=429,
                was_success=False,
            )
        )

        # Calculate time since last 429
        time_since_last_429 = now - self.last_429_time if self.last_429_time > 0 else float("inf")
        self.last_429_time = now

        # Aggressive backoff for rapid 429s (within 30 seconds)
        if time_since_last_429 < 30:
            # Very aggressive - double the delay
            multiplier = 2.0
        elif time_since_last_429 < 60:
            # Moderate - increase by 50%
            multiplier = 1.5
        else:
            # Standard - increase by 25%
            multiplier = 1.25

        # Additional penalty for consecutive 429s
        if self.consecutive_429s >= 3:
            multiplier *= 1.5

        old_delay = self.current_delay
        self.current_delay = min(self.max_delay, self.current_delay * multiplier)

        logger.warning(
            f"[{self.host}] 429 received! Delay: {old_delay:.2f}s -> {self.current_delay:.2f}s "
            f"(consecutive: {self.consecutive_429s}, total: {self.total_429s}, "
            f"time_since_last: {time_since_last_429:.1f}s)"
        )

    def get_recent_429_rate(self, window_seconds: float = 300) -> float:
        """Calculate 429 rate in the last N seconds."""
        now = time.time()
        cutoff = now - window_seconds
        recent_events = [e for e in self.events if e.timestamp > cutoff]
        if not recent_events:
            return 0.0
        rate_limit_events = [e for e in recent_events if e.status_code == 429]
        return len(rate_limit_events) / len(recent_events)

    def get_delay(self) -> float:
        """Get current delay with jitter."""
        import random

        # Add jitter: ±20% to avoid synchronized requests
        jitter = random.uniform(0.8, 1.2)
        return self.current_delay * jitter


class AdaptiveRateLimiter:
    """Manages per-host adaptive rate limiting.

    This class tracks rate limit responses (429s) per host and dynamically
    adjusts delays to avoid getting blocked. It uses a sliding window
    approach to detect rate limit patterns and adjusts accordingly.
    """

    def __init__(self, default_delay: float = 2.0):
        """Initialize rate limiter.

        Args:
            default_delay: Default delay between requests in seconds
        """
        self.default_delay = default_delay
        self._host_states: dict[str, HostRateLimitState] = {}
        self._lock = asyncio.Lock()

    def _get_host_state(self, host: str) -> HostRateLimitState:
        """Get or create rate limit state for a host."""
        if host not in self._host_states:
            self._host_states[host] = HostRateLimitState(
                host=host,
                base_delay=self.default_delay,
                current_delay=self.default_delay,
            )
        return self._host_states[host]

    def record_success(self, url: str):
        """Record a successful request."""
        host = urlparse(url).netloc
        state = self._get_host_state(host)
        state.record_success()

    def record_429(self, url: str):
        """Record a 429 rate limit response."""
        host = urlparse(url).netloc
        state = self._get_host_state(host)
        state.record_429()

    def get_delay(self, url: str) -> float:
        """Get the current delay for a URL's host."""
        host = urlparse(url).netloc
        state = self._get_host_state(host)
        return state.get_delay()

    async def wait(self, url: str, last_request_time: float) -> float:
        """Wait for appropriate delay before making a request.

        Args:
            url: URL to request
            last_request_time: Time of last request

        Returns:
            Current time after waiting
        """
        async with self._lock:
            current_time = time.time()
            delay = self.get_delay(url)
            time_since_last = current_time - last_request_time

            if time_since_last < delay:
                sleep_time = delay - time_since_last
                logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f}s (adaptive delay: {delay:.2f}s)")
                await asyncio.sleep(sleep_time)

            return time.time()

    def get_stats(self) -> dict:
        """Get rate limiting statistics for all hosts."""
        return {
            host: {
                "current_delay": state.current_delay,
                "total_429s": state.total_429s,
                "total_requests": state.total_requests,
                "recent_429_rate": state.get_recent_429_rate(),
            }
            for host, state in self._host_states.items()
        }


class AdaptiveConcurrencyLimiter:
    """Dynamically adjusts crawler worker concurrency based on host feedback."""

    def __init__(self, min_limit: int, max_limit: int):
        self._min_limit = max(1, min_limit)
        self._max_limit = max(self._min_limit, max_limit)
        self._limit = self._min_limit
        self._peak_limit = self._limit
        self._active = 0
        self._peak_active = 0
        self._success_streak = 0
        self._last_rate_limit_at = 0.0
        self._condition = asyncio.Condition()

    async def acquire(self):
        async with self._condition:
            await self._condition.wait_for(lambda: self._active < self._limit)
            self._active += 1
            self._peak_active = max(self._peak_active, self._active)

    async def release(self):
        async with self._condition:
            self._active = max(0, self._active - 1)
            self._condition.notify_all()

    async def record_success(self):
        async with self._condition:
            self._success_streak += 1
            window_clear = (time.time() - self._last_rate_limit_at) >= 60
            if self._limit < self._max_limit and self._success_streak >= 25 and window_clear:
                self._limit += 1
                self._peak_limit = max(self._peak_limit, self._limit)
                self._success_streak = 0
                self._condition.notify_all()

    async def record_rate_limit(self):
        async with self._condition:
            new_limit = max(self._min_limit, self._limit // 2)
            self._limit = min(self._limit, new_limit)
            self._success_streak = 0
            self._last_rate_limit_at = time.time()
            self._condition.notify_all()

    def snapshot(self) -> dict[str, int]:
        return {
            "current_limit": self._limit,
            "peak_limit": self._peak_limit,
            "active_workers": self._active,
            "peak_active": self._peak_active,
        }


@dataclass
class CrawlConfig:
    """Configuration for crawler behavior."""

    user_agent: str = ""  # Will be randomly selected from config.USER_AGENTS if empty
    timeout: int = 30
    delay_seconds: float = 2.0  # Increased delay to avoid bot detection - was 1.0
    max_pages: int | None = None  # None = no limit
    same_host_only: bool = True  # Don't wander off-site
    allow_querystrings: bool = False  # Most docs don't need ?highlight= etc.
    max_retries: int = 3
    progress_interval: int = 10  # Report progress every N pages
    on_url_discovered: Callable[[str], None] | None = None  # Callback for progressive processing
    headless: bool = True  # Playwright headless mode for debugging
    # Idempotency support
    skip_recently_visited: Callable[[str], bool] | None = None  # Callback to check if URL was recently fetched
    force_crawl: bool = False  # If True, ignore idempotency and crawl all URLs
    markdown_url_suffix: str | None = None  # Optional suffix to emit Markdown mirror URLs


@dataclass
class PageProcessResult:
    """Outcome of processing a single page."""

    success: bool
    rate_limited: bool = False


class EfficientCrawler:
    """BFS-based crawler optimized for documentation sites.

    Features:
    - Uses sets for O(1) URL lookups (visited tracking)
    - Deque-based frontier for efficient BFS
    - Configurable rate limiting
    - Retry logic with exponential backoff
    - Honors URL whitelist/blacklist from config
    - Progress reporting
    """

    def __init__(
        self,
        start_urls: set[str],
        crawl_config: CrawlConfig | None = None,
        settings: Settings | None = None,
    ):
        """Initialize crawler.

        Args:
            start_urls: Set of URLs to start crawling from
            crawl_config: Optional crawler configuration
            settings: Optional Settings instance (required if using ES metadata storage)
        """
        self.start_urls = start_urls
        self.config = crawl_config or CrawlConfig()
        self.settings = settings

        # Use sets for O(1) lookups
        self.visited: set[str] = set()
        self._scheduled: set[str] = set()
        self.collected: set[str] = set()
        self.output_collected: set[str] = set()
        self._normalized_seed_urls: set[str] = set()
        suffix_preference = self.config.markdown_url_suffix
        if not suffix_preference and self.settings:
            suffix_preference = getattr(self.settings, "markdown_url_suffix", "")
        self._markdown_url_suffix = (suffix_preference or "").strip()

        # Deque maintained for backward compatibility/tests; actual crawl uses async queue
        self.frontier: deque[str] = deque()
        self._url_queue: asyncio.Queue[str] | None = None
        self._concurrency: AdaptiveConcurrencyLimiter | None = None
        self._stop_crawl = False

        # HTTP client with retry logic
        self.client: httpx.AsyncClient | None = None

        # Rate limiting - use adaptive rate limiter
        self._last_request_time: float = 0.0
        self._last_url: str | None = None  # For referer headers
        self._rate_limiter = AdaptiveRateLimiter(default_delay=self.config.delay_seconds)

        # Idempotency tracking
        self._crawler_skipped: int = 0  # Count of URLs skipped due to recent visit

        # Cookie management
        self._cookies: httpx.Cookies = httpx.Cookies()
        self._cookie_storage_key = f"crawler_cookies_{hash(tuple(sorted(start_urls)))}"

        # Extract common host from start URLs for validation
        self.allowed_hosts: set[str] = set()
        for url in start_urls:
            parsed = urlparse(url)
            self.allowed_hosts.add(parsed.netloc)

        logger.info(f"Initialized crawler with {len(start_urls)} start URLs")
        logger.info(f"Allowed hosts: {self.allowed_hosts}")

    async def __aenter__(self):
        """Async context manager entry."""
        self.client = self._create_client()
        await self._load_cookies()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self._save_cookies()
        if self.client:
            await self.client.aclose()

    def _create_client(self) -> httpx.AsyncClient:
        """Create HTTP client with retry configuration."""
        import os

        # Select random User-Agent from settings if not specified
        user_agent = self.config.user_agent
        if not user_agent and self.settings:
            user_agent = self.settings.get_random_user_agent()

        # Check if we need proxy configuration
        http_proxy = os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")
        https_proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or http_proxy

        if http_proxy:
            logger.debug(f"Using proxy: http={http_proxy}, https={https_proxy}")
            # Create proxy-aware transport
            transport = httpx.AsyncHTTPTransport(
                retries=self.config.max_retries,
            )
        else:
            logger.debug("No proxy configured")
            transport = httpx.AsyncHTTPTransport(
                retries=self.config.max_retries,
            )

        timeout = httpx.Timeout(
            self.config.timeout,
            connect=10.0,
        )

        # Enhanced headers to match real browser exactly
        headers = {
            "User-Agent": user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
            ),
            "Accept-Language": "en,en-US;q=0.9",
            "Accept-Encoding": "gzip, deflate",  # Removed br - some servers send different content with brotli
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
            "Sec-Ch-Ua": '"Microsoft Edge";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Priority": "u=0, i",
        }

        return httpx.AsyncClient(
            transport=transport,
            timeout=timeout,
            headers=headers,
            follow_redirects=True,
            verify=True,  # Enable SSL verification for security
            proxy=http_proxy if http_proxy else None,
            cookies=self._cookies,  # Use persistent cookie jar
        )

    async def _load_cookies(self):
        """Load cookies from filesystem storage."""
        import json

        # Try filesystem first
        cookie_file = self._get_cookie_file_path()

        try:
            if cookie_file.exists():
                cookie_data = json.loads(cookie_file.read_text()).get("cookies", {})

                # Restore cookies from stored data
                for name, value in cookie_data.items():
                    if isinstance(value, dict):
                        # Structured cookie data
                        self._cookies.set(
                            name=name,
                            value=value.get("value", ""),
                            domain=value.get("domain", ""),
                            path=value.get("path", "/"),
                        )
                    else:
                        # Simple name=value cookie
                        self._cookies.set(name, value)

                logger.debug(f"Loaded {len(cookie_data)} cookies from filesystem")
                return
        except Exception as e:
            logger.debug(f"Failed to load cookies from filesystem: {e}")

    def _get_cookie_file_path(self):
        """Get the filesystem path for cookie storage.

        Returns:
            Path to cookie JSON file
        """
        from pathlib import Path

        # Use /tmp for cookie storage
        cookie_dir = Path("/tmp/docs-mcp-server/crawler-cookies")
        cookie_dir.mkdir(parents=True, exist_ok=True)

        # Use hash of start URLs as filename
        return cookie_dir / f"{self._cookie_storage_key}.json"

    async def _save_cookies(self):
        """Save cookies to filesystem storage."""
        import json

        cookie_file = self._get_cookie_file_path()

        try:
            # Convert cookies to serializable format
            cookie_data = {}
            for cookie in self._cookies.jar:
                cookie_data[cookie.name] = {
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path,
                    "expires": cookie.expires,
                    "secure": cookie.secure,
                }

            # Save to filesystem
            document = {
                "cookies": cookie_data,
                "updated_at": time.time(),
                "url_set": list(self.start_urls)[:5],  # Store first 5 URLs for reference
            }

            cookie_file.write_text(json.dumps(document, indent=2))
            logger.debug(f"Saved {len(cookie_data)} cookies to filesystem")
        except Exception as e:
            logger.debug(f"Failed to save cookies: {e}")

    async def crawl(self) -> set[str]:
        """Execute BFS crawl from start URLs.

        Returns:
            Set of all discovered URLs
        """
        if not self.client:
            raise RuntimeError("Crawler must be used as async context manager")

        seed_urls = self._initialize_frontier()
        self.output_collected.clear()

        self._url_queue = asyncio.Queue()
        for url in seed_urls:
            self._url_queue.put_nowait(url)
        self._stop_crawl = False

        configured_min = getattr(self.settings, "crawler_min_concurrency", len(seed_urls) or 1)
        configured_max = getattr(self.settings, "crawler_max_concurrency", configured_min)
        max_sessions = getattr(self.settings, "crawler_max_sessions", configured_max)
        worker_pool_size = max(1, min(max_sessions, configured_max))
        min_limit = max(1, min(configured_min, worker_pool_size))
        self._concurrency = AdaptiveConcurrencyLimiter(min_limit, worker_pool_size)

        logger.info(
            "Starting BFS crawl with %s seed URLs (workers=%s, min=%s, max=%s)",
            len(seed_urls),
            worker_pool_size,
            min_limit,
            worker_pool_size,
        )

        start_time = time.time()
        progress_lock = asyncio.Lock()
        progress_state = {"last_report": 0}

        workers = [
            asyncio.create_task(self._crawl_worker(start_time, progress_state, progress_lock))
            for _ in range(worker_pool_size)
        ]

        await self._url_queue.join()
        for _ in workers:
            await self._url_queue.put(None)
        await asyncio.gather(*workers)

        self._url_queue = None
        self._concurrency = None
        self._stop_crawl = False

        self._log_completion(start_time)
        combined_results = set(self.collected)
        combined_results.update(self.output_collected)
        return combined_results

    def _initialize_frontier(self):
        """Initialize crawl frontier with start URLs."""
        self.frontier.clear()
        self._scheduled.clear()
        deduped_seeds: set[str] = set()
        normalized_seeds: list[str] = []

        # Iterate deterministically so breadth-first order is predictable during tests
        for url in sorted(self.start_urls):
            logger.debug(f"Processing start URL: {url}")
            normalized = self._normalize_url(url)
            logger.debug(f"Normalized URL: {normalized}")
            if not normalized:
                logger.warning(f"Failed to normalize: {url}")
                continue

            should_process = self._should_process_url(normalized)
            logger.debug(f"Should process {normalized}: {should_process}")
            if not should_process:
                logger.warning(f"Filtered out: {normalized}")
                continue

            if normalized in deduped_seeds:
                logger.debug(f"Skipping duplicate seed URL: {normalized}")
                continue

            deduped_seeds.add(normalized)
            normalized_seeds.append(normalized)

        for normalized in normalized_seeds:
            self.frontier.append(normalized)
            self._scheduled.add(normalized)
            logger.info(f"Added to frontier: {normalized}")

        self._normalized_seed_urls = set(normalized_seeds)
        return normalized_seeds

    def _should_stop_crawl(self) -> bool:
        """Check if crawl should stop due to page limit."""
        if self.config.max_pages and len(self.collected) >= self.config.max_pages:
            logger.info(f"Reached max_pages limit ({self.config.max_pages})")
            return True
        return False

    def _should_report_progress(self, last_report: int) -> bool:
        """Check if progress should be reported."""
        return len(self.collected) - last_report >= self.config.progress_interval

    def _report_progress(self, start_time: float):
        """Report crawl progress."""
        elapsed = time.time() - start_time
        rate = len(self.collected) / elapsed if elapsed > 0 else 0
        pending = len(self.frontier)
        if self._url_queue is not None:
            pending = self._url_queue.qsize()
        logger.info(
            f"Progress: {len(self.collected)} collected, "
            f"{pending} in queue, "
            f"{len(self.visited)} visited "
            f"({rate:.1f} pages/sec)"
        )

    def _remove_from_frontier(self, url: str):
        if not self.frontier:
            return

        if self.frontier and self.frontier[0] == url:
            self.frontier.popleft()
            return

        try:
            self.frontier.remove(url)
        except ValueError:
            # Frontier and queue can diverge when tests pre-populate frontier
            pass

    async def _maybe_report_progress(self, start_time: float, progress_state: dict, progress_lock: asyncio.Lock):
        async with progress_lock:
            if self._should_report_progress(progress_state["last_report"]):
                self._report_progress(start_time)
                progress_state["last_report"] = len(self.collected)

    def _log_completion(self, start_time: float):
        """Log crawl completion statistics."""
        elapsed = time.time() - start_time
        rate = len(self.collected) / elapsed if elapsed > 0 else 0
        skipped_msg = f", {self._crawler_skipped} skipped (recently visited)" if self._crawler_skipped > 0 else ""
        logger.info(
            f"Crawl complete: {len(self.collected)} pages collected in {elapsed:.1f}s "
            f"({rate:.1f} pages/sec){skipped_msg}"
        )

        # Log rate limiter stats
        rate_stats = self._rate_limiter.get_stats()
        for host, stats in rate_stats.items():
            if stats["total_429s"] > 0:
                logger.info(
                    f"Rate limit stats for {host}: "
                    f"{stats['total_429s']}/{stats['total_requests']} requests were 429s, "
                    f"final delay: {stats['current_delay']:.2f}s"
                )

    async def _crawl_worker(self, start_time: float, progress_state: dict, progress_lock: asyncio.Lock):
        """Worker that processes URLs from the frontier queue."""

        assert self._url_queue is not None
        assert self._concurrency is not None

        while True:
            url = await self._url_queue.get()

            if url is None:
                self._url_queue.task_done()
                return

            self._remove_from_frontier(url)

            if self._stop_crawl or self._should_stop_crawl():
                self._stop_crawl = True
                self._scheduled.discard(url)
                self._url_queue.task_done()
                continue

            if url in self.visited:
                self._scheduled.discard(url)
                self._url_queue.task_done()
                continue

            await self._concurrency.acquire()
            result: PageProcessResult | None = None
            should_requeue = False

            try:
                result = await self._process_page(url)
                if result and result.rate_limited and not result.success:
                    should_requeue = True
            except Exception:  # pragma: no cover - defensive logging
                logger.exception(f"Worker failed on {url}")
            finally:
                if result:
                    if result.rate_limited:
                        await self._concurrency.record_rate_limit()
                    elif result.success:
                        await self._concurrency.record_success()

                if result and result.success:
                    self.visited.add(url)

                await self._concurrency.release()

                if should_requeue:
                    self.frontier.append(url)
                    self._scheduled.add(url)
                    await self._url_queue.put(url)
                else:
                    self._scheduled.discard(url)

                await self._maybe_report_progress(start_time, progress_state, progress_lock)
                self._url_queue.task_done()

    @staticmethod
    def _coerce_fetch_result(result: str | None | tuple[str | None, bool]) -> tuple[str | None, bool]:
        """Normalize fetch results to a (content, rate_limited) tuple."""

        if isinstance(result, tuple) and len(result) == 2:
            content, rate_limited = result
            return content, bool(rate_limited)
        return result, False

    async def _process_page(self, url: str) -> PageProcessResult:
        """Fetch and process a single page.

        Args:
            url: URL to process
        """
        # Type narrowing: client is initialized in __aenter__
        assert self.client is not None, "Crawler must be used within async context manager"

        # Apply rate limiting (pass URL for per-host tracking)
        await self._apply_rate_limit(url)

        # Add referer header for subsequent requests to look more browser-like
        headers = {}
        if hasattr(self, "_last_url") and self._last_url:
            headers["Referer"] = self._last_url

        # Determine which method to try first based on crawler_playwright_first setting
        use_playwright_first = False
        if self.settings and hasattr(self.settings, "crawler_playwright_first"):
            use_playwright_first = self.settings.crawler_playwright_first

        # Fetch content using appropriate strategy
        if use_playwright_first:
            fetch_result = await self._fetch_with_playwright_first(
                url,
                headers,
                include_rate_limit=True,
            )
        else:
            fetch_result = await self._fetch_with_httpx_first(
                url,
                headers,
                include_rate_limit=True,
            )

        html_content, rate_limited = self._coerce_fetch_result(fetch_result)

        if html_content is None:
            logger.error(f"Failed to fetch content for {url}")
            return PageProcessResult(success=False, rate_limited=rate_limited)

        # HTML page - collect and extract links
        self.collected.add(url)
        converted_current = self._convert_to_markdown_url(url, is_seed=url in self._normalized_seed_urls)
        self.output_collected.add(converted_current)
        logger.debug(f"Collected HTML: {url}")
        logger.debug(f"Response content length: {len(html_content)} chars")
        self._last_url = url  # Store for next request's referer header

        # Extract and queue links
        links = self._extract_links(html_content, url)
        queued = 0

        logger.debug(f"Extracted {len(links)} links from {url}")

        for link in links:
            normalized = self._normalize_url(link)
            if not normalized:
                continue

            if normalized in self.visited or normalized in self._scheduled:
                logger.debug(f"Skipping already visited: {normalized}")
                continue

            if not self._should_process_url(normalized):
                logger.debug(f"Skipping filtered URL: {normalized}")
                continue

            self.frontier.append(normalized)
            self._scheduled.add(normalized)
            if self._url_queue is not None:
                await self._url_queue.put(normalized)
            else:
                logger.debug("Queue is not initialized; frontier only")
            queued += 1
            logger.debug(f"Queued: {normalized}")

            converted_discovery = self._convert_to_markdown_url(normalized, is_seed=False)

            # Notify discovery callback only for URLs that pass filters
            if self.config.on_url_discovered:
                try:
                    self.config.on_url_discovered(converted_discovery)
                except Exception as e:
                    logger.warning(f"URL discovery callback failed for {converted_discovery}: {e}")

        logger.info(f"Queued {queued} new links from {url}")

        if queued > 0:
            logger.debug(f"Queued {queued} new links from {url}")

        return PageProcessResult(success=True, rate_limited=rate_limited)

    async def _fetch_with_playwright_first(
        self,
        url: str,
        headers: dict,
        *,
        include_rate_limit: bool = False,
    ) -> str | None | tuple[str | None, bool]:
        """Fetch content using Playwright-first approach with httpx fallback."""
        assert self.client is not None, "Client must be initialized"

        logger.debug(f"Using Playwright-first approach for {url}")
        rate_limited = False

        def format_result(content: str | None) -> str | None | tuple[str | None, bool]:
            return (content, rate_limited) if include_rate_limit else content

        try:
            from article_extractor import PlaywrightFetcher

            async with PlaywrightFetcher(headless=self.config.headless) as fetcher:
                html_content, status_code = await fetcher.fetch(url)
                # Check for rate limit even from Playwright
                if status_code == 429:
                    self._rate_limiter.record_429(url)
                    rate_limited = True
                    # Wait for adaptive delay before continuing
                    delay = self._rate_limiter.get_delay(url)
                    logger.warning(f"Playwright got 429 for {url}, backing off {delay:.2f}s")
                    await asyncio.sleep(delay)
                    return format_result(None)
                logger.debug(f"Playwright succeeded for {url} (status: {status_code})")
                self._rate_limiter.record_success(url)
                return format_result(html_content)
        except OSError as os_error:
            # Handle "Too many open files" by backing off
            if os_error.errno == 24:  # EMFILE
                logger.warning(f"File descriptor exhaustion for {url}, backing off 30s...")
                await asyncio.sleep(30)
                return format_result(None)
            logger.warning(f"Playwright failed for {url}: {os_error}, trying httpx...")
        except Exception as pw_error:
            logger.warning(f"Playwright failed for {url}: {pw_error}, trying httpx...")

        # Fallback to httpx
        try:
            response = await self.client.get(url, headers=headers)
            if response.status_code == 429:
                self._rate_limiter.record_429(url)
                logger.warning(f"httpx got 429 for {url}")
                return None, True
            response.raise_for_status()
            logger.debug(f"httpx fallback succeeded for {url}")
            self._rate_limiter.record_success(url)
            return format_result(response.text)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                self._rate_limiter.record_429(url)
                rate_limited = True
                return format_result(None)
            logger.error(f"Both Playwright and httpx failed for {url}: httpx={e}")
            return format_result(None)
        except Exception as http_error:
            logger.error(f"Both Playwright and httpx failed for {url}: httpx={http_error}")
            return format_result(None)

    async def _fetch_with_httpx_first(
        self,
        url: str,
        headers: dict,
        *,
        include_rate_limit: bool = False,
    ) -> str | None | tuple[str | None, bool]:
        """Fetch content using httpx-first approach (legacy) with Playwright fallback."""
        assert self.client is not None, "Client must be initialized"

        logger.debug(f"Using httpx-first approach for {url}")
        max_retries = 3
        rate_limited = False

        def format_result(content: str | None) -> str | None | tuple[str | None, bool]:
            return (content, rate_limited) if include_rate_limit else content

        for attempt in range(max_retries):
            try:
                response = await self.client.get(url, headers=headers)
                if response.status_code == 429:
                    self._rate_limiter.record_429(url)
                    rate_limited = True
                    delay = self._rate_limiter.get_delay(url)
                    logger.warning(f"httpx got 429 for {url}, backing off {delay:.2f}s before retry {attempt + 1}")
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                self._rate_limiter.record_success(url)
                return format_result(response.text)
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code == 429:
                    self._rate_limiter.record_429(url)
                    rate_limited = True
                    delay = self._rate_limiter.get_delay(url)
                    logger.warning(f"httpx raised 429 for {url}, backing off {delay:.2f}s before retry {attempt + 1}")
                    await asyncio.sleep(delay)
                    continue
                if status_code in (403, 404, 503):
                    wait_time = (attempt + 1) * 5.0
                    logger.warning(
                        f"httpx got {status_code} for {url}, waiting {wait_time:.1f}s before retry {attempt + 1}"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                logger.warning(f"HTTP status error for {url}: {status_code}")
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                delay = self.config.delay_seconds * (attempt + 1)
                logger.warning(f"Network error for {url} ({exc}), retrying in {delay:.2f}s")
                await asyncio.sleep(delay)
            except Exception as http_error:
                logger.error(f"HTTP fetch failed for {url}: {http_error}")
                break

        try:
            from article_extractor import PlaywrightFetcher

            async with PlaywrightFetcher(headless=self.config.headless) as fetcher:
                html_content, status_code = await fetcher.fetch(url)
                if status_code == 429:
                    self._rate_limiter.record_429(url)
                    rate_limited = True
                    delay = self._rate_limiter.get_delay(url)
                    logger.warning(f"Playwright fallback got 429 for {url}, backing off {delay:.2f}s")
                    await asyncio.sleep(delay)
                    return format_result(None)
                self._rate_limiter.record_success(url)
                return format_result(html_content)
        except OSError as os_error:
            if getattr(os_error, "errno", None) == 24:  # EMFILE
                logger.warning(f"Playwright fallback hit EMFILE for {url}, backing off 30s...")
                await asyncio.sleep(30)
                return format_result(None)
            logger.warning(f"Playwright fallback failed for {url}: {os_error}")
        except Exception as pw_error:
            logger.warning(f"Playwright fallback failed for {url}: {pw_error}")

        return format_result(None)

    def _extract_links(self, html: str, base_url: str) -> set[str]:
        """Extract links from HTML content.

        Args:
            html: HTML content
            base_url: Base URL for resolving relative links

        Returns:
            Set of absolute URLs
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            links: set[str] = set()

            # Find ALL elements with href attributes, not just <a> tags
            # AWS docs use custom elements and divs with href for navigation
            for element in soup.find_all(attrs={"href": True}):
                href = element["href"]
                # BeautifulSoup can return list for attribute values, ensure it's a string
                if isinstance(href, list):
                    href = href[0] if href else ""
                if isinstance(href, str):
                    absolute = urljoin(base_url, href)
                    links.add(absolute)

            return links
        except Exception as e:
            logger.debug(f"Failed to extract links from {base_url}: {e}")
            return set()

    def _supports_markdown_suffix(self) -> bool:
        return bool(self._markdown_url_suffix)

    def _convert_to_markdown_url(self, url: str, *, is_seed: bool) -> str:
        """Convert a normalized HTML URL to its Markdown mirror when configured."""

        if is_seed or not self._supports_markdown_suffix():
            return url

        try:
            parsed = urlparse(url)
            path = parsed.path or "/"
            trimmed_path = path.rstrip("/")
            if not trimmed_path:
                return url

            suffix = self._markdown_url_suffix
            assert suffix is not None

            if trimmed_path.endswith(suffix):
                markdown_path = trimmed_path
            else:
                last_segment = trimmed_path.split("/")[-1]
                if "." in last_segment:
                    _base, ext = last_segment.rsplit(".", 1)
                    if ext.lower() in {"html", "htm"}:
                        trimmed_path = trimmed_path[: -(len(ext) + 1)]
                    else:
                        return url
                markdown_path = f"{trimmed_path}{suffix}"

            normalized = urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    markdown_path,
                    parsed.params,
                    parsed.query if self.config.allow_querystrings else "",
                    "",
                )
            )
            return normalized
        except Exception as exc:  # pragma: no cover - defensive guardrail
            logger.debug(f"Failed to convert {url} to markdown variant: {exc}")
            return url

    def _normalize_url(self, url: str) -> str | None:
        """Normalize URL by removing fragments and optionally query strings.

        Args:
            url: URL to normalize

        Returns:
            Normalized URL or None if invalid
        """
        try:
            # Remove fragment
            url, _frag = urldefrag(url)

            parsed = urlparse(url)

            # Skip non-http(s) URLs
            if parsed.scheme not in ("http", "https"):
                return None

            # Remove query string if not allowed
            query = parsed.query if self.config.allow_querystrings else ""

            # Use path as-is (no trailing slash normalization - let redirects guide canonical form)
            path = parsed.path or "/"

            normalized = urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    path,
                    parsed.params,
                    query,
                    "",  # No fragment
                )
            )

            return normalized

        except Exception as e:
            logger.debug(f"Failed to normalize URL {url}: {e}")
            return None

    def _should_process_url(self, url: str) -> bool:
        """Check if URL should be processed based on whitelist/blacklist.

        Args:
            url: URL to check

        Returns:
            True if URL should be processed
        """
        # First check file extension to avoid fetching non-HTML files
        parsed = urlparse(url)
        path = parsed.path.lower()

        # Skip non-HTML file extensions
        non_html_extensions = {
            ".css",
            ".js",
            ".json",
            ".xml",
            ".txt",
            ".pdf",
            ".zip",
            ".tar",
            ".gz",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".ico",
            ".webp",
            ".bmp",
            ".mp3",
            ".mp4",
            ".avi",
            ".mov",
            ".wav",
            ".flv",
            ".wmv",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
            ".otf",
        }

        if any(path.endswith(ext) for ext in non_html_extensions):
            logger.debug(f"Skipping non-HTML file extension: {url}")
            return False

        # Use config's filtering logic (if settings available)
        if self.settings:
            return self.settings.should_process_url(url)

        # No settings available - accept all HTML URLs
        return True

    def _should_crawl_url(self, url: str) -> bool:
        """Check if URL should be crawled (includes host checks).

        Args:
            url: URL to check

        Returns:
            True if URL should be crawled
        """
        parsed = urlparse(url)

        # Check host restriction
        if self.config.same_host_only and parsed.netloc not in self.allowed_hosts:
            logger.debug(f"Host check failed for {url}: {parsed.netloc} not in {self.allowed_hosts}")
            return False

        logger.debug(f"Host checks passed for {url}")
        return True

    async def _apply_rate_limit(self, url: str | None = None):
        """Apply adaptive rate limiting between requests.

        Uses the AdaptiveRateLimiter to dynamically adjust delays based on
        429 response frequency per host.

        Args:
            url: URL being requested (used for per-host rate limiting)
        """
        if self.config.delay_seconds > 0 and url:
            self._last_request_time = await self._rate_limiter.wait(url, self._last_request_time)
        elif self.config.delay_seconds > 0:
            # Fallback to simple delay if no URL provided
            current_time = time.time()
            time_since_last = current_time - self._last_request_time
            if time_since_last < self.config.delay_seconds:
                await asyncio.sleep(self.config.delay_seconds - time_since_last)
            self._last_request_time = time.time()
