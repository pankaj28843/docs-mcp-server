"""Bounded same-host link discovery over the shared browser runtime."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Self
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

from lxml import html

from ..runtime.cdp_browser import BrowserRuntimeProtocol


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RenderedCrawlConfig:
    """Policy inputs for one bounded discovery pass."""

    timeout: float
    max_pages: int
    same_host_only: bool
    allow_querystrings: bool
    on_url_discovered: Callable[[str], None] | None
    skip_recently_visited: Callable[[str], bool] | None
    force_crawl: bool
    markdown_url_suffix: str | None
    user_agent_provider: Callable[[], str]
    should_process_url: Callable[[str], bool]
    max_concurrency: int
    proxy: str | None
    browser_runtime: BrowserRuntimeProtocol | None


class RenderedCrawler:
    """Concurrent BFS crawler whose only rendering owner is AppBuilder."""

    def __init__(self, start_urls: set[str], config: RenderedCrawlConfig) -> None:
        self._start_urls = start_urls
        self._config = config
        self._allowed_hosts = {urlsplit(url).netloc for url in start_urls}
        self._crawler_skipped = 0

    @property
    def skipped_count(self) -> int:
        return self._crawler_skipped

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    async def crawl(self) -> set[str]:
        """Return seeds and recursively discovered URLs up to max_pages."""
        if self._config.browser_runtime is None:
            raise RuntimeError("Rendered discovery requires the shared browser runtime")
        seed_urls = {url for seed in sorted(self._start_urls) if (url := self._normalize(seed))}
        scheduled = set(seed_urls)
        queue = deque(sorted(scheduled))
        collected: set[str] = set()
        claimed = 0
        first_error: Exception | None = None
        concurrency = max(1, min(self._config.max_concurrency, self._config.max_pages))

        while queue and claimed < self._config.max_pages:
            batch: list[str] = []
            while queue and len(batch) < concurrency and claimed < self._config.max_pages:
                url = queue.popleft()
                if self._should_skip(url):
                    self._crawler_skipped += 1
                    collected.add(url)
                    continue
                batch.append(url)
                claimed += 1
            if not batch:
                continue

            pages = await asyncio.gather(
                *(
                    self._config.browser_runtime.fetch(
                        url,
                        user_agent=self._config.user_agent_provider(),
                        proxy=self._config.proxy,
                        timeout_seconds=self._config.timeout,
                    )
                    for url in batch
                ),
                return_exceptions=True,
            )
            for url, page in zip(batch, pages, strict=True):
                if isinstance(page, BaseException):
                    if isinstance(page, asyncio.CancelledError):
                        raise page
                    if first_error is None:
                        first_error = page
                    logger.warning("Rendered discovery failed for %s: %s", url, page)
                    continue
                if page.status_code != 200 or not page.html:
                    continue
                collected.add(url)
                for link in self._extract_links(page.html, url):
                    normalized = self._normalize(link)
                    if normalized is None or normalized in scheduled:
                        continue
                    scheduled.add(normalized)
                    queue.append(normalized)
                    if self._config.on_url_discovered:
                        self._config.on_url_discovered(self._output_url(normalized))

        if first_error is not None and not collected:
            raise first_error
        return {self._output_url(url, is_seed=url in seed_urls) for url in collected}

    def _should_skip(self, url: str) -> bool:
        return bool(
            not self._config.force_crawl
            and self._config.skip_recently_visited
            and self._config.skip_recently_visited(url)
        )

    def _normalize(self, url: str) -> str | None:
        defragmented, _ = urldefrag(url)
        parsed = urlsplit(defragmented)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        if self._config.same_host_only and parsed.netloc not in self._allowed_hosts:
            return None
        query = parsed.query if self._config.allow_querystrings else ""
        normalized = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", query, ""))
        return normalized if self._config.should_process_url(normalized) else None

    @staticmethod
    def _extract_links(html_content: str, base_url: str) -> set[str]:
        document = html.fromstring(html_content)
        return {urljoin(base_url, href.strip()) for href in document.xpath("//a[@href]/@href") if href.strip()}

    def _output_url(self, url: str, *, is_seed: bool = False) -> str:
        suffix = self._config.markdown_url_suffix
        if not suffix or is_seed or urlsplit(url).path.endswith(suffix):
            return url
        parsed = urlsplit(url)
        return urlunsplit((parsed.scheme, parsed.netloc, f"{parsed.path}{suffix}", parsed.query, ""))
