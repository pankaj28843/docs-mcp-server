#!/usr/bin/env python3
"""Discover Apple Developer documentation URLs from rendered DocC pages.

Apple's public documentation pages are hydrated by JavaScript. This operator tool
uses the installed ``cdp`` CLI to visit rendered pages, extract same-prefix
``https://developer.apple.com/documentation/`` links, and crawl that graph in BFS
order. The resulting URL list can be passed to ``scripts/apple_docc_snapshot.py``
so existing public docs are rendered and indexed instead of being missed by the
DocC JSON graph alone.
"""

from __future__ import annotations

import argparse
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit
import urllib.request


LOGGER = logging.getLogger(__name__)

DOCUMENTATION_PREFIX = "https://developer.apple.com/documentation/"
DEFAULT_URLS_FILE = Path("tmp/apple-docc-snapshot/apple-developer/rendered-bfs-urls.json")
DEFAULT_STATE_FILE = Path("tmp/apple-docc-snapshot/apple-developer/rendered-bfs-state.json")
DEFAULT_DOCC_SEED_DATA_URLS = (
    "https://developer.apple.com/tutorials/data/documentation.json",
    "https://developer.apple.com/tutorials/data/documentation/technologies.json",
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
READY_EXPRESSION = 'document.readyState !== "loading" && document.querySelectorAll("a[href]").length > 0'
LINK_EXPRESSION = r"""
(() => {
  const stripBomPrefix = (href) => {
    let value = String(href || "").trimStart();
    for (let i = 0; i < 8; i += 1) {
      value = value.replace(/^\ufeff+/, "");
      const lower = value.toLowerCase();
      if (!lower.startsWith("%ef%bb%bf") && !lower.startsWith("%25")) break;
      try {
        const decoded = decodeURIComponent(value);
        if (decoded === value) break;
        value = decoded;
      } catch (_error) {
        break;
      }
    }
    return value.replace(/^\ufeff+/, "");
  };
  const links = Array.from(document.querySelectorAll("a"))
    .map((x) => x.getAttribute("href"))
    .map(stripBomPrefix)
    .map((href) => {
      try {
        return new URL(href, window.location.href).toString();
      } catch (_error) {
        return "";
      }
    })
    .filter((x) => x.startsWith("https://developer.apple.com/documentation/"));
  return JSON.stringify(Array.from(new Set(links)).sort());
})()
""".strip()
_DOC_IDENTIFIER_PATTERN = re.compile(r"doc://[^\s\"']*/documentation/([^\s\"'#]+)")
_DOC_PATH_PATTERN = re.compile(r"^/documentation/([^#?]+)")


class AppleRenderedLinkBfsError(RuntimeError):
    """Raised when rendered Apple documentation link discovery cannot continue."""


@dataclass(frozen=True)
class RenderedLinkBfsOptions:
    """Configuration for one rendered-link BFS crawl."""

    start_urls: tuple[str, ...] = (DOCUMENTATION_PREFIX,)
    urls_file: Path = DEFAULT_URLS_FILE
    state_file: Path = DEFAULT_STATE_FILE
    limit: int = 0
    retries: int = 2
    checkpoint_every: int = 25
    reset: bool = False
    skip_preflight: bool = False
    delay_seconds: float = 0.0
    seed_docc_root_groups: bool = False
    scope_terms: tuple[str, ...] = ()
    include_url_regexes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RenderedLinkBfsResult:
    """Summary of a rendered-link BFS crawl."""

    discovered_urls: int
    visited_pages: int
    queued_pages: int
    failed_pages: int
    urls_file: Path
    state_file: Path


@dataclass
class _RenderedLinkBfsState:
    queue: deque[str]
    queued: set[str]
    visited: set[str]
    discovered: set[str]
    failures: dict[str, int]


class CdpBrowser:
    """Small wrapper around cdp commands used by the BFS crawler."""

    def __init__(
        self,
        *,
        command: str = "cdp",
        page_timeout: str = "45s",
        wait_timeout: str = "15s",
        settle_seconds: float = 2.0,
        poll_seconds: float = 1.0,
    ) -> None:
        self.command = command
        self.page_timeout = page_timeout
        self.wait_timeout = wait_timeout
        self.settle_seconds = settle_seconds
        self.poll_seconds = poll_seconds
        self.target_id: str | None = None

    def preflight(self) -> None:
        """Verify the installed cdp command surface before browser work."""
        if shutil.which(self.command) is None:
            raise AppleRenderedLinkBfsError(f"cdp command not found on PATH: {self.command}")
        for args in (("--help",), ("open", "--help"), ("eval", "--help"), ("wait", "eval", "--help")):
            self._run_text(args, timeout="10s")

    def extract_links(self, url: str) -> tuple[str, ...]:
        """Open one rendered page and return normalized documentation links from its anchors."""
        try:
            self.target_id = self._open(url, target_id=self.target_id)
        except AppleRenderedLinkBfsError:
            if self.target_id is None:
                raise
            LOGGER.warning("cdp target became stale; opening a new tab for %s", url)
            self.target_id = self._open(url, target_id=None)

        self._wait_for_anchors(self.target_id)
        return self._wait_for_stable_links(self.target_id)

    def _open(self, url: str, *, target_id: str | None) -> str:
        args = ["--timeout", self.page_timeout, "open", url, "--json"]
        if target_id:
            args.extend(("--new-tab=false", "--target", target_id))
        payload = self._run_json(tuple(args))
        page = payload.get("page") if isinstance(payload.get("page"), dict) else payload.get("target")
        if not isinstance(page, dict) or not isinstance(page.get("id"), str):
            raise AppleRenderedLinkBfsError(f"cdp open did not return a page id for {url}")
        return page["id"]

    def _wait_for_anchors(self, target_id: str) -> None:
        try:
            self._run_json(
                ("--timeout", self.wait_timeout, "wait", "eval", READY_EXPRESSION, "--target", target_id, "--json")
            )
        except AppleRenderedLinkBfsError as exc:
            LOGGER.warning("cdp wait for anchors failed; evaluating links anyway: %s", exc)

    def _wait_for_stable_links(self, target_id: str) -> tuple[str, ...]:
        deadline = time.monotonic() + (_duration_seconds(self.wait_timeout) or 15.0)
        stable_since: float | None = None
        previous_links: tuple[str, ...] | None = None
        latest_links: tuple[str, ...] = ()
        while time.monotonic() <= deadline:
            latest_links = self._evaluate_links(target_id)
            now = time.monotonic()
            if latest_links and latest_links == previous_links:
                stable_since = stable_since or now
                if now - stable_since >= self.settle_seconds:
                    return latest_links
            else:
                stable_since = now if latest_links else None
                previous_links = latest_links
            time.sleep(self.poll_seconds)
        LOGGER.warning("cdp link set did not settle within %s; using %s links", self.wait_timeout, len(latest_links))
        return latest_links

    def _evaluate_links(self, target_id: str) -> tuple[str, ...]:
        payload = self._run_json(
            ("--timeout", self.page_timeout, "eval", LINK_EXPRESSION, "--target", target_id, "--json")
        )
        return _links_from_eval_payload(payload)

    def _run_json(self, args: Sequence[str]) -> dict[str, Any]:
        output = self._run_text(args, timeout=_duration_seconds(args[1]) if args and args[0] == "--timeout" else None)
        try:
            payload = json.loads(output or "{}")
        except json.JSONDecodeError as exc:
            raise AppleRenderedLinkBfsError(
                f"cdp emitted non-JSON output for {' '.join(args)}: {output[:500]}"
            ) from exc
        if not isinstance(payload, dict):
            raise AppleRenderedLinkBfsError(f"cdp emitted unexpected JSON for {' '.join(args)}")
        return payload

    def _run_text(self, args: Sequence[str], *, timeout: str | float | None = None) -> str:
        seconds = _duration_seconds(timeout) if isinstance(timeout, str) else timeout
        command = [self.command, *args]
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=seconds + 5 if seconds else None,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise AppleRenderedLinkBfsError(f"cdp failed ({completed.returncode}) for {' '.join(args)}: {detail}")
        return completed.stdout


def crawl_rendered_documentation_links(
    options: RenderedLinkBfsOptions,
    *,
    browser: CdpBrowser | None = None,
) -> RenderedLinkBfsResult:
    """Crawl rendered Apple documentation links in BFS order and write URL/state files."""
    scope_patterns = _scope_patterns(options)
    start_urls = _normalized_start_urls(_seed_start_urls(options, scope_patterns))
    browser = browser or CdpBrowser()
    if options.reset and options.state_file.exists():
        options.state_file.unlink()
    state = _read_state(options.state_file) if options.state_file.exists() else _new_state(start_urls)
    for start_url in start_urls:
        _enqueue(state, start_url)

    if not options.skip_preflight:
        browser.preflight()

    pages_since_checkpoint = 0
    while state.queue and (options.limit <= 0 or len(state.visited) < options.limit):
        url = state.queue.popleft()
        state.queued.discard(url)
        if url in state.visited:
            continue

        try:
            links = browser.extract_links(url)
        except Exception as exc:
            attempts = state.failures.get(url, 0) + 1
            state.failures[url] = attempts
            if attempts <= options.retries:
                state.queue.append(url)
                state.queued.add(url)
                LOGGER.warning("failed to crawl %s (attempt %s/%s): %s", url, attempts, options.retries + 1, exc)
            else:
                LOGGER.error("giving up on %s after %s attempts: %s", url, attempts, exc)
            _checkpoint(options, state)
            continue

        state.visited.add(url)
        if _url_allowed_by_scope(url, scope_patterns) and indexable_documentation_url(url):
            state.discovered.add(url)
        new_links = 0
        for link in links:
            normalized = normalize_documentation_url(link)
            if normalized is None or not _url_allowed_by_scope(normalized, scope_patterns):
                continue
            if indexable_documentation_url(normalized):
                state.discovered.add(normalized)
            if _enqueue(state, normalized):
                new_links += 1

        pages_since_checkpoint += 1
        LOGGER.info(
            "visited=%s discovered=%s queue=%s links=%s new=%s url=%s",
            len(state.visited),
            len(state.discovered),
            len(state.queue),
            len(links),
            new_links,
            url,
        )
        if options.delay_seconds > 0:
            time.sleep(options.delay_seconds)
        if options.checkpoint_every > 0 and pages_since_checkpoint >= options.checkpoint_every:
            _checkpoint(options, state)
            pages_since_checkpoint = 0

    _checkpoint(options, state)
    failed_pages = sum(
        1 for url, attempts in state.failures.items() if url not in state.visited and attempts > options.retries
    )
    return RenderedLinkBfsResult(
        discovered_urls=len(state.discovered),
        visited_pages=len(state.visited),
        queued_pages=len(state.queue),
        failed_pages=failed_pages,
        urls_file=options.urls_file,
        state_file=options.state_file,
    )


def _seed_start_urls(options: RenderedLinkBfsOptions, scope_patterns: Sequence[re.Pattern[str]]) -> tuple[str, ...]:
    if not options.seed_docc_root_groups:
        return options.start_urls
    root_group_urls = discover_docc_root_group_urls(
        include_url_regexes=tuple(pattern.pattern for pattern in scope_patterns)
    )
    LOGGER.info("seeded %s root groups from Apple DocC JSON", len(root_group_urls))
    return (*options.start_urls, *root_group_urls)


def discover_docc_root_group_urls(
    data_urls: Sequence[str] = DEFAULT_DOCC_SEED_DATA_URLS,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    include_url_regexes: Sequence[str] = (),
) -> tuple[str, ...]:
    """Fetch Apple DocC roots and return documentation root-group URLs."""
    groups: set[str] = set()
    for data_url in data_urls:
        request = urllib.request.Request(data_url, headers={"User-Agent": user_agent, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise AppleRenderedLinkBfsError(f"failed to fetch Apple DocC seed data {data_url}: {exc}") from exc
        groups.update(extract_root_groups_from_docc_payload(payload))
    urls = tuple(f"{DOCUMENTATION_PREFIX}{quote(group, safe='-._~():')}" for group in sorted(groups, key=str.lower))
    patterns = _compile_scope_patterns(include_url_regexes)
    return tuple(url for url in urls if _url_allowed_by_scope(url, patterns))


def extract_root_groups_from_docc_payload(payload: Any) -> set[str]:
    """Extract first path segments below /documentation/ from a DocC JSON payload."""
    groups: set[str] = set()

    def add(raw_path: str) -> None:
        parts = tuple(part for part in raw_path.strip().strip("/").split("/") if part)
        if parts and not parts[0].startswith("_"):
            groups.add(parts[0])

    def walk(value: Any) -> None:
        if isinstance(value, str):
            for match in _DOC_IDENTIFIER_PATTERN.finditer(value):
                add(match.group(1))
            if match := _DOC_PATH_PATTERN.match(value):
                add(match.group(1))
            return
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
            return
        if isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return groups


def _scope_patterns(options: RenderedLinkBfsOptions) -> tuple[re.Pattern[str], ...]:
    return _compile_scope_patterns(
        (*options.include_url_regexes, *tuple(_scope_term_pattern(term) for term in options.scope_terms if term))
    )


def _scope_term_pattern(term: str) -> str:
    escaped = re.escape(term.strip())
    return rf"(^|[^A-Za-z0-9]){escaped}([^A-Za-z0-9]|$)" if escaped else ""


def _compile_scope_patterns(include_url_regexes: Sequence[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in include_url_regexes if pattern)


def _url_allowed_by_scope(url: str, scope_patterns: Sequence[re.Pattern[str]]) -> bool:
    if not scope_patterns:
        return True
    if normalize_documentation_url(url) == DOCUMENTATION_PREFIX:
        return True
    return any(pattern.search(url) for pattern in scope_patterns)


def normalize_documentation_url(url: str) -> str | None:
    """Normalize and whitelist public Apple documentation URLs."""
    try:
        parsed = urlsplit(_strip_leading_bom_url_prefix(url))
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.netloc.lower() != "developer.apple.com":
        return None
    path = parsed.path or "/"
    if path == "/documentation":
        path = "/documentation/"
    if not path.startswith("/documentation/"):
        return None
    if _malformed_documentation_path(path):
        return None
    if path != "/documentation/":
        path = path.rstrip("/")
    return urlunsplit(("https", "developer.apple.com", path, "", ""))


def _strip_leading_bom_url_prefix(url: str) -> str:
    candidate = url.strip().lstrip("\ufeff")
    for _ in range(8):
        lowered = candidate.lower()
        if not lowered.startswith("%ef%bb%bf") and not lowered.startswith("%25"):
            break
        decoded = unquote(candidate)
        if decoded == candidate:
            break
        candidate = decoded.lstrip("\ufeff")
    return candidate.lstrip("\ufeff")


def _malformed_documentation_path(path: str) -> bool:
    candidate = path
    for _ in range(8):
        lowered = candidate.lower()
        if "\ufeff" in candidate or "developer.apple.com/" in lowered or re.search(r"https?:/+", lowered):
            return True
        decoded = unquote(candidate)
        if decoded == candidate:
            break
        candidate = decoded
    return False


def indexable_documentation_url(url: str) -> str | None:
    """Return a normalized non-root documentation URL, or None for non-doc/root URLs."""
    normalized = normalize_documentation_url(url)
    if normalized is None:
        return None
    path = urlsplit(normalized).path[len("/documentation/") :].strip("/")
    return normalized if path else None


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the rendered-link BFS CLI parser."""
    parser = argparse.ArgumentParser(description="BFS crawl rendered Apple Developer Documentation links with cdp")
    parser.add_argument("--start-url", action="append", default=[], help="Documentation URL to seed; repeatable")
    parser.add_argument("--urls-file", type=Path, default=DEFAULT_URLS_FILE)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--limit", type=int, default=0, help="Maximum rendered pages to visit; 0 means no cap")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--reset", action="store_true", help="Ignore existing crawl state and start from the seed URLs")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip cdp --help command-surface checks")
    parser.add_argument("--preflight-only", action="store_true", help="Verify cdp command help and exit")
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds to sleep between page visits")
    parser.add_argument(
        "--seed-docc-root-groups",
        action="store_true",
        help="Fetch Apple DocC roots and seed BFS with every first-level documentation group",
    )
    parser.add_argument("--scope-term", action="append", default=[], help="Only crawl URLs containing this term")
    parser.add_argument("--include-url-regex", action="append", default=[], help="Only crawl URLs matching this regex")
    parser.add_argument("--cdp-command", default="cdp")
    parser.add_argument("--page-timeout", default="45s")
    parser.add_argument("--wait-timeout", default="15s")
    parser.add_argument("--settle-seconds", type=float, default=2.0, help="Required stable rendered link-set duration")
    parser.add_argument("--poll-seconds", type=float, default=1.0, help="Rendered link-set polling interval")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the rendered-link BFS CLI."""
    args = build_argument_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper()), format="%(message)s")
    browser = CdpBrowser(
        command=args.cdp_command,
        page_timeout=args.page_timeout,
        wait_timeout=args.wait_timeout,
        settle_seconds=args.settle_seconds,
        poll_seconds=args.poll_seconds,
    )
    if args.preflight_only:
        try:
            browser.preflight()
        except AppleRenderedLinkBfsError as exc:
            LOGGER.error("Apple rendered-link BFS preflight failed: %s", exc)
            return 1
        LOGGER.info("Apple rendered-link BFS cdp preflight OK")
        return 0

    options = RenderedLinkBfsOptions(
        start_urls=tuple(args.start_url) if args.start_url else (DOCUMENTATION_PREFIX,),
        urls_file=args.urls_file,
        state_file=args.state_file,
        limit=args.limit,
        retries=args.retries,
        checkpoint_every=args.checkpoint_every,
        reset=args.reset,
        skip_preflight=args.skip_preflight,
        delay_seconds=args.delay,
        seed_docc_root_groups=args.seed_docc_root_groups,
        scope_terms=tuple(args.scope_term),
        include_url_regexes=tuple(args.include_url_regex),
    )
    try:
        result = crawl_rendered_documentation_links(options, browser=browser)
    except AppleRenderedLinkBfsError as exc:
        LOGGER.error("Apple rendered-link BFS failed: %s", exc)
        return 1

    LOGGER.info("Apple rendered-link BFS complete")
    LOGGER.info("  discovered URLs: %s", result.discovered_urls)
    LOGGER.info("  visited pages:    %s", result.visited_pages)
    LOGGER.info("  queued pages:     %s", result.queued_pages)
    LOGGER.info("  failed pages:     %s", result.failed_pages)
    LOGGER.info("  urls file:        %s", result.urls_file)
    LOGGER.info("  state file:       %s", result.state_file)
    return 0 if result.discovered_urls > 0 else 1


def _normalized_start_urls(urls: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(url for raw_url in urls if (url := normalize_documentation_url(raw_url))))
    if not normalized:
        raise AppleRenderedLinkBfsError(
            "at least one --start-url must be under https://developer.apple.com/documentation/"
        )
    return normalized


def _new_state(start_urls: Sequence[str]) -> _RenderedLinkBfsState:
    queue = deque(start_urls)
    return _RenderedLinkBfsState(queue=queue, queued=set(queue), visited=set(), discovered=set(), failures={})


def _read_state(path: Path) -> _RenderedLinkBfsState:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AppleRenderedLinkBfsError(f"state file must contain a JSON object: {path}")
    queue = deque(
        url
        for raw_url in payload.get("queue", [])
        if isinstance(raw_url, str) and (url := normalize_documentation_url(raw_url))
    )
    visited = {
        url
        for raw_url in payload.get("visited", [])
        if isinstance(raw_url, str) and (url := normalize_documentation_url(raw_url))
    }
    discovered = {
        url
        for raw_url in payload.get("discovered", [])
        if isinstance(raw_url, str) and (url := indexable_documentation_url(raw_url))
    }
    raw_failures = payload.get("failures") if isinstance(payload.get("failures"), dict) else {}
    failures = {
        normalized: int(count)
        for url, count in raw_failures.items()
        if (normalized := normalize_documentation_url(str(url)))
    }
    return _RenderedLinkBfsState(
        queue=queue, queued=set(queue), visited=visited, discovered=discovered, failures=failures
    )


def _enqueue(state: _RenderedLinkBfsState, url: str) -> bool:
    if url in state.visited or url in state.queued:
        return False
    state.queue.append(url)
    state.queued.add(url)
    return True


def _checkpoint(options: RenderedLinkBfsOptions, state: _RenderedLinkBfsState) -> None:
    _write_json_atomic(options.state_file, _state_payload(state))
    _write_json_atomic(options.urls_file, sorted(state.discovered, key=str.lower))


def _state_payload(state: _RenderedLinkBfsState) -> dict[str, Any]:
    return {
        "queue": list(state.queue),
        "visited": sorted(state.visited, key=str.lower),
        "discovered": sorted(state.discovered, key=str.lower),
        "failures": dict(sorted(state.failures.items())),
    }


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _links_from_eval_payload(payload: dict[str, Any]) -> tuple[str, ...]:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    raw_value = result.get("value") if isinstance(result, dict) else None
    if isinstance(raw_value, str):
        try:
            values = json.loads(raw_value)
        except json.JSONDecodeError:
            values = raw_value.splitlines()
    elif isinstance(raw_value, list):
        values = raw_value
    else:
        values = []
    return tuple(
        dict.fromkeys(url for value in values if isinstance(value, str) and (url := normalize_documentation_url(value)))
    )


def _duration_seconds(value: str | float | None) -> float | None:
    if value is None or isinstance(value, float):
        return value
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m|h)?", value.strip())
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2) or "s"
    return amount / 1000 if unit == "ms" else amount * {"s": 1, "m": 60, "h": 3600}[unit]


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
