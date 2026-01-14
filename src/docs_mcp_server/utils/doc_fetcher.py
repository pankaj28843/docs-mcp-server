"""Documentation fetcher using pure-Python article-extractor plus remote fallback.

Primary extraction happens locally via Playwright + article-extractor. When Readability
fails, we optionally fan out to an HTTP fallback endpoint that runs the same
article-extractor build inside a separate service.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from article_extractor import ArticleResult, ExtractionOptions, extract_article
from article_extractor.fetcher import PlaywrightFetcher
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from ..config import Settings
from ..observability.tracing import create_span
from .models import DocPage, ReadabilityContent


logger = logging.getLogger(__name__)


class DocFetchError(RuntimeError):
    """Raised when all extraction strategies fail for a URL."""

    def __init__(self, reason: str, detail: str | None = None):
        message = detail if detail else reason
        super().__init__(message)
        self.reason = reason
        self.detail = detail


class AsyncDocFetcher:
    """High-performance async documentation fetcher with Playwright + article-extractor."""

    def __init__(
        self,
        settings: Settings,
    ):
        """Initialize fetcher with configuration.

        Args:
            settings: Settings instance with all configuration
        """
        self.settings = settings
        self.http_timeout = settings.http_timeout
        self.max_concurrent_requests = settings.max_concurrent_requests
        self.request_delay_ms = settings.request_delay_ms
        self.snippet_length = settings.snippet_length
        self.markdown_url_suffix = getattr(settings, "markdown_url_suffix", "")
        self.fallback_enabled = getattr(settings, "fallback_extractor_enabled", False)
        self.fallback_endpoint = getattr(settings, "fallback_extractor_endpoint", "").rstrip("/")
        self.fallback_timeout = getattr(settings, "fallback_extractor_timeout_seconds", 20)
        self.fallback_batch_size = getattr(settings, "fallback_extractor_batch_size", 1)
        self.fallback_max_retries = getattr(settings, "fallback_extractor_max_retries", 2)
        self.fallback_api_key = getattr(settings, "fallback_extractor_api_key", None)
        self._fallback_attempts = 0
        self._fallback_successes = 0
        self._fallback_failures = 0

        self.session: aiohttp.ClientSession | None = None
        self.playwright_fetcher: PlaywrightFetcher | None = None  # type: ignore[valid-type]
        self.semaphore = asyncio.Semaphore(self.max_concurrent_requests)

        # Rate limiting
        self._last_request_time = 0.0
        self._request_delay = self.request_delay_ms / 1000.0

        # Extraction options for article-extractor
        self._extraction_options = ExtractionOptions(
            min_word_count=150,  # Minimum words for valid content
            include_images=False,
            include_code_blocks=True,
            safe_markdown=True,
        )

    async def __aenter__(self):
        """Async context manager entry."""
        self._create_session()

        # Initialize Playwright fetcher for primary content retrieval
        if not self.playwright_fetcher:
            try:
                fetcher = PlaywrightFetcher()
                await fetcher.__aenter__()
                self.playwright_fetcher = fetcher
                logger.info("PlaywrightFetcher initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize PlaywrightFetcher: {e}", exc_info=True)
                # Clean up failed fetcher
                self.playwright_fetcher = None
                await self._close_session()
                raise

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self._close_session()
        if self.playwright_fetcher:
            await self.playwright_fetcher.__aexit__(exc_type, exc_val, exc_tb)

    def _build_session_components(self) -> tuple[aiohttp.ClientTimeout, aiohttp.TCPConnector, dict[str, str]]:
        """Build HTTP session components with optimized settings."""
        timeout = aiohttp.ClientTimeout(
            total=self.http_timeout,
            connect=10,
            sock_read=30,
        )

        connector = aiohttp.TCPConnector(
            limit=self.max_concurrent_requests,
            limit_per_host=5,
            ttl_dns_cache=300,
            use_dns_cache=True,
        )

        headers = {
            "User-Agent": self.settings.get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        return timeout, connector, headers

    def _create_session(self):  # pragma: no cover
        """Create HTTP session with optimized settings."""
        timeout, connector, headers = self._build_session_components()

        self.session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers=headers,
        )

    async def _close_session(self) -> None:
        """Close the aiohttp session if it was created."""
        if self.session:
            await self.session.close()
            self.session = None

    async def fetch_page(self, url: str) -> DocPage | None:
        """Fetch and parse a documentation page.

        Strategy:
        1. Check for direct markdown mirrors first
        2. Fetch HTML with Playwright (handles Cloudflare/JS)
        3. Extract content with article-extractor (pure Python)
        """
        if not self.session:
            self._create_session()

        url_parts = urlsplit(url)
        with create_span(
            "fetch.page",
            kind=SpanKind.INTERNAL,
            attributes={
                "fetch.fallback_enabled": self.fallback_enabled,
                "fetch.markdown_suffix_enabled": bool(self.markdown_url_suffix),
                "url.host": url_parts.netloc,
                "url.path": url_parts.path,
            },
        ) as span:
            async with self.semaphore:
                await self._apply_rate_limit()

                # Prefer Markdown mirrors when suffix configured (e.g., Twilio *.md endpoints)
                direct_markdown = await self._fetch_direct_markdown(url)
                if direct_markdown:
                    span.add_event("fetch.direct_markdown.hit", {})
                    logger.debug("Served %s via direct markdown mirror", url)
                    return direct_markdown

                # Fetch with Playwright + extract with article-extractor
                if self.playwright_fetcher:
                    span.add_event("fetch.playwright.start", {})
                    result = await self._fetch_and_extract(url)
                    if result:
                        span.add_event("fetch.playwright.success", {})
                        logger.debug("Playwright + article-extractor successful for %s", url)
                        return result
                    span.add_event("fetch.playwright.failure", {})
                    logger.debug("Playwright + article-extractor failed for %s", url)

                span.add_event("fetch.fallback.start", {"fallback.enabled": self.fallback_enabled})
                fallback_page, fallback_reason = await self._fetch_with_fallback(url)
                if fallback_page:
                    span.add_event("fetch.fallback.success", {})
                    return fallback_page
                span.add_event("fetch.fallback.failure", {"reason": fallback_reason or "extraction_failed"})

                reason = fallback_reason or "extraction_failed"
                detail = f"All extraction methods failed for {url}"
                logger.error(detail)
                raise DocFetchError(reason, detail=detail)

    async def _fetch_and_extract(self, url: str) -> DocPage | None:
        """Fetch with Playwright and extract using article-extractor.

        This implements pure-Python extraction without external services.
        """
        if not self.playwright_fetcher:
            logger.error(f"PlaywrightFetcher not initialized when trying to fetch {url}")
            return None

        if not hasattr(self.playwright_fetcher, "_context") or self.playwright_fetcher._context is None:
            logger.error(f"PlaywrightFetcher context not initialized when trying to fetch {url}")
            return None

        try:
            # Fetch HTML with Playwright (handles Cloudflare, JS rendering)
            html_content, status_code = await self.playwright_fetcher.fetch(url)
            if not html_content or status_code != 200:
                logger.debug(f"Playwright fetch failed for {url}: status {status_code}")
                return None

            # Extract content using article-extractor (pure Python)
            extraction_result = extract_article(html_content, url, self._extraction_options)

            if not extraction_result.success:
                logger.debug(f"Article extraction failed for {url}: {extraction_result.error}")
                return None

            return self._convert_to_doc_page(url, extraction_result)

        except Exception as e:
            logger.error(f"Error in Playwright + article-extractor for {url}: {e}", exc_info=True)
            return None

    def _convert_to_doc_page(self, url: str, result: ArticleResult) -> DocPage | None:
        """Convert ArticleResult to DocPage for compatibility."""
        if not result.content and not result.markdown:
            logger.debug(f"No content extracted for {url}")
            return None

        # Use markdown from article-extractor directly
        markdown_content = result.markdown
        clean_markdown = self._clean_markdown(markdown_content)

        # Generate excerpt
        excerpt = self._generate_excerpt(result, clean_markdown)

        # Extract title with fallback
        title = self._extract_title(result, url)

        return DocPage(
            url=url,
            title=title,
            content=clean_markdown,
            extraction_method="article_extractor",
            readability_content=ReadabilityContent(
                raw_html=result.content,
                extracted_content=result.content,
                processed_markdown=clean_markdown,
                excerpt=excerpt,
                score=None,  # article-extractor doesn't expose score
                success=True,
                extraction_method="article_extractor",
            ),
        )

    def _extract_title(self, result: ArticleResult, url: str) -> str:
        """Extract title from result with URL fallback."""
        if result.title:
            return result.title.strip()

        if result.excerpt:
            first_sentence = result.excerpt.split(".")[0].strip()
            if first_sentence and len(first_sentence) > 10:
                return first_sentence

        return self._derive_url_title(url)

    def _generate_excerpt(self, result: ArticleResult, markdown_content: str) -> str:
        """Generate optimized excerpt for search results."""
        # Prefer article-extractor excerpt if available
        if result.excerpt and len(result.excerpt) > 50:
            return self._truncate_excerpt(result.excerpt)

        # Generate from markdown content
        lines = markdown_content.split("\n")
        content_lines = [line.strip() for line in lines if line.strip() and not line.startswith("#")]

        if content_lines:
            excerpt = " ".join(content_lines[:5])
            return self._truncate_excerpt(excerpt)

        return self._truncate_excerpt(markdown_content)

    async def _apply_rate_limit(self):
        """Apply rate limiting between requests."""
        current_time = asyncio.get_event_loop().time()
        time_since_last = current_time - self._last_request_time
        if time_since_last < self._request_delay:
            await asyncio.sleep(self._request_delay - time_since_last)
        self._last_request_time = asyncio.get_event_loop().time()

    def _clean_markdown(self, markdown: str) -> str:
        """Clean up the markdown content."""
        lines = markdown.split("\n")
        cleaned_lines = []

        for line in lines:
            # Remove excessive blank lines
            if line.strip() or (cleaned_lines and cleaned_lines[-1].strip()):
                cleaned_lines.append(line)

        # Join and clean up whitespace
        content = "\n".join(cleaned_lines)

        # Remove excessive whitespace
        content = re.sub(r"\n{3,}", "\n\n", content)
        content = re.sub(r"[ \t]+", " ", content)

        return content.strip()

    def _prepare_direct_markdown(self, markdown: str) -> str:
        """Normalize direct markdown mirrors without stripping formatting."""
        if not markdown:
            return ""

        content = markdown.lstrip("\ufeff")  # Drop BOM if present
        content = content.replace("\r\n", "\n")
        if not content.strip():
            return ""

        normalized_lines: list[str] = []
        previous_blank = False
        for line in content.split("\n"):
            stripped = line.strip()
            if not stripped:
                if previous_blank:
                    continue
                previous_blank = True
                normalized_lines.append("")
                continue

            indentation = len(line) - len(line.lstrip(" "))
            body = line[indentation:]

            # Only collapse spaces for prose-like lines; keep gaps inside code spans
            if not body.lstrip().startswith("```"):
                body = re.sub(r"(?<!`) {3,}", "  ", body)

            normalized_lines.append(" " * indentation + body)
            previous_blank = False

        content = "\n".join(normalized_lines)
        if not content.endswith("\n"):
            content = f"{content}\n"

        return content

    def _build_markdown_candidate_url(self, url: str) -> str | None:
        suffix = (self.markdown_url_suffix or "").strip()
        if not suffix:
            return None

        parsed = urlsplit(url)
        path = parsed.path or "/"
        trimmed_path = path.rstrip("/")
        if not trimmed_path:
            return None

        if trimmed_path.endswith(suffix):
            markdown_path = trimmed_path
        else:
            last_segment = trimmed_path.split("/")[-1]
            if "." in last_segment:
                _base, ext = last_segment.rsplit(".", 1)
                if ext.lower() in {"html", "htm"}:
                    trimmed_path = trimmed_path[: -(len(ext) + 1)]
                else:
                    return None
            markdown_path = f"{trimmed_path}{suffix}"

        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                markdown_path,
                parsed.query,
                "",
            )
        )

    def _derive_markdown_title(self, markdown: str, fallback_url: str) -> str:
        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                heading = stripped.lstrip("#").strip()
                if heading:
                    return heading

        return self._derive_url_title(fallback_url)

    def _derive_url_title(self, url: str) -> str:
        parts = url.rstrip("/").split("/")
        if parts and parts[-1]:
            return parts[-1].replace("-", " ").title()
        return url

    def _generate_excerpt_from_markdown_text(self, markdown: str) -> str:
        lines = [line.strip() for line in markdown.split("\n") if line.strip()]
        if not lines:
            return ""
        excerpt = " ".join(lines[:5])
        return self._truncate_excerpt(excerpt)

    def _truncate_excerpt(self, text: str) -> str:
        max_length = self.snippet_length
        if len(text) > max_length:
            return f"{text[:max_length]}..."
        return text

    async def _fetch_with_fallback(self, url: str) -> tuple[DocPage | None, str | None]:  # noqa: PLR0912
        if not self.fallback_enabled or not self.fallback_endpoint:
            span = trace.get_current_span()
            if span.is_recording():
                span.add_event("fetch.fallback.disabled", {})
            return None, "fallback_disabled"
        if self._should_skip_fallback(url):
            logger.debug("Skipping fallback extractor for asset-like URL %s", url)
            span = trace.get_current_span()
            if span.is_recording():
                span.add_event("fetch.fallback.skipped", {"reason": "asset_like_url"})
            return None, "fallback_skipped_asset"

        if not self.session:
            self._create_session()
        assert self.session is not None

        timeout = aiohttp.ClientTimeout(total=self.fallback_timeout)
        headers = {"Content-Type": "application/json"}
        if self.fallback_api_key:
            headers["Authorization"] = f"Bearer {self.fallback_api_key}"

        payload = {"url": url}
        attempt = 0
        delay_seconds = 1.0
        last_error: Exception | None = None
        self._fallback_attempts += 1

        while attempt <= self.fallback_max_retries:
            try:
                span = trace.get_current_span()
                if span.is_recording():
                    span.add_event("fetch.fallback.attempt", {"attempt": attempt + 1})
                response = await self.session.post(
                    self.fallback_endpoint,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )

                if response.status != 200:
                    snippet = (await response.text())[:200]
                    last_error = RuntimeError(f"status={response.status} body={snippet}")
                else:
                    payload_json = await response.json()
                    doc_page = self._convert_fallback_payload(url, payload_json)
                    if doc_page:
                        logger.info("Fallback extractor succeeded for %s", url)
                        span = trace.get_current_span()
                        if span.is_recording():
                            span.add_event("fetch.fallback.response", {"status": response.status})
                        self._fallback_successes += 1
                        return doc_page, None
                    last_error = RuntimeError("fallback returned empty payload")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - network best effort
                last_error = exc
                logger.warning("Fallback extractor attempt %s failed for %s: %s", attempt + 1, url, exc)

            attempt += 1
            if attempt <= self.fallback_max_retries:
                await asyncio.sleep(delay_seconds)
                delay_seconds = min(delay_seconds * 2, 8.0)

        if last_error:
            logger.error("Fallback extractor exhausted retries for %s: %s", url, last_error)
        self._fallback_failures += 1
        reason = str(last_error) if last_error else "fallback_exhausted"
        return None, reason

    def _convert_fallback_payload(self, url: str, payload: dict[str, Any]) -> DocPage | None:
        markdown = payload.get("markdown") or payload.get("content_markdown") or payload.get("processed_markdown") or ""
        html_content = payload.get("content") or payload.get("html") or ""
        if not markdown and html_content:
            markdown = html_content
        if not markdown.strip():
            return None

        cleaned = self._clean_markdown(markdown)
        title = payload.get("title") or self._derive_markdown_title(cleaned, url)
        excerpt = payload.get("excerpt") or self._generate_excerpt_from_markdown_text(cleaned)
        extracted_content = html_content or cleaned
        return self._build_markdown_doc_page(
            url=url,
            title=title,
            markdown=cleaned,
            excerpt=excerpt,
            raw_html=html_content,
            extracted_content=extracted_content,
            extraction_method="article_extractor_fallback",
        )

    def _should_skip_fallback(self, url: str) -> bool:
        parsed = urlsplit(url)
        path = (parsed.path or "").lower()
        if "/_static/" in path:
            return True
        binary_suffixes = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".pdf", ".zip", ".css", ".js")
        return path.endswith(binary_suffixes)

    def get_fallback_metrics(self) -> dict[str, int]:
        return {
            "fallback_attempts": self._fallback_attempts,
            "fallback_successes": self._fallback_successes,
            "fallback_failures": self._fallback_failures,
        }

    async def _fetch_direct_markdown(self, url: str) -> DocPage | None:
        if not self.markdown_url_suffix:
            return None

        candidate_url = self._build_markdown_candidate_url(url)
        if not candidate_url:
            return None

        if not self.session:
            self._create_session()

        assert self.session is not None

        try:
            response = await self.session.get(candidate_url)
            if response.status != 200:
                logger.debug("Markdown mirror unavailable for %s (status %s)", url, response.status)
                return None
            raw_markdown = await response.text()
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("Markdown mirror fetch failed for %s: %s", url, exc)
            return None

        if not raw_markdown.strip():
            return None

        prepared_markdown = self._prepare_direct_markdown(raw_markdown)
        if not prepared_markdown:
            return None
        title = self._derive_markdown_title(prepared_markdown, url)
        excerpt = self._generate_excerpt_from_markdown_text(prepared_markdown)
        return self._build_markdown_doc_page(
            url=url,
            title=title,
            markdown=prepared_markdown,
            excerpt=excerpt,
            raw_html=raw_markdown,
            extracted_content=prepared_markdown,
            extraction_method="direct_markdown",
        )

    def _build_markdown_doc_page(
        self,
        *,
        url: str,
        title: str,
        markdown: str,
        excerpt: str,
        raw_html: str,
        extracted_content: str,
        extraction_method: str,
    ) -> DocPage:
        readability_content = ReadabilityContent(
            raw_html=raw_html,
            extracted_content=extracted_content,
            processed_markdown=markdown,
            excerpt=excerpt,
            score=None,
            success=True,
            extraction_method=extraction_method,
        )
        return DocPage(
            url=url,
            title=title,
            content=markdown,
            extraction_method=extraction_method,
            readability_content=readability_content,
        )


# Export the main classes and functions
__all__ = [
    "AsyncDocFetcher",
    "DocFetchError",
    "DocPage",
]
