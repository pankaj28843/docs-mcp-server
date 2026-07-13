"""Proxy-pool selection and block detection helpers."""

from __future__ import annotations

from collections.abc import Iterable


BLOCKED_STATUS_CODES = frozenset({403, 407, 408, 425, 429})
RETRYABLE_PROXY_STATUS_CODES = BLOCKED_STATUS_CODES | frozenset({500, 502, 503, 504})


def normalize_proxy_list(proxies: Iterable[str | None]) -> list[str]:
    """Return unique, non-empty proxies while preserving configured order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for proxy in proxies:
        value = (proxy or "").strip()
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


class ProxyPool:
    """Sticky proxy pool with round-robin rotation after blocked responses."""

    def __init__(self, proxies: Iterable[str | None]):
        self._proxies = tuple(normalize_proxy_list(proxies))
        self._active_index: int | None = 0 if self._proxies else None

    @property
    def proxies(self) -> tuple[str, ...]:
        return self._proxies

    @property
    def has_proxies(self) -> bool:
        return bool(self._proxies)

    def candidates(self) -> list[str | None]:
        """Return the active proxy first, then remaining proxies in round-robin order."""
        if not self._proxies:
            return [None]

        start = self._active_index or 0
        return [self._proxies[(start + offset) % len(self._proxies)] for offset in range(len(self._proxies))]

    def mark_success(self, proxy: str | None) -> None:
        if proxy is None:
            return
        try:
            self._active_index = self._proxies.index(proxy)
        except ValueError:
            return

    def mark_blocked(self, proxy: str | None) -> None:
        if proxy is None or not self._proxies:
            return
        try:
            blocked_index = self._proxies.index(proxy)
        except ValueError:
            return

        if self._active_index in (None, blocked_index):
            self._active_index = (blocked_index + 1) % len(self._proxies)


def proxy_label(proxy: str | None) -> str:
    return proxy or "direct"


def has_blocked_body(content: bytes | str | None) -> bool:
    if not content:
        return False

    if isinstance(content, bytes):
        sample = content[:8192].decode("utf-8", errors="ignore").lower()
    else:
        sample = content[:8192].lower()

    google_sorry = any(
        marker in sample
        for marker in (
            "google.com/sorry",
            "our systems have detected unusual traffic",
            "unusual traffic from your computer network",
            "to continue, please type the characters below",
        )
    ) or ("<title>sorry" in sample and "google" in sample)
    cloudflare_block = "attention required! | cloudflare" in sample and "ray id" in sample
    recaptcha_block = ("recaptcha" in sample or "g-recaptcha" in sample) and (
        "unusual traffic" in sample or "automated queries" in sample
    )
    return google_sorry or cloudflare_block or recaptcha_block


def should_rotate_proxy(status_code: int, content: bytes | str | None = None) -> bool:
    return status_code in RETRYABLE_PROXY_STATUS_CODES or has_blocked_body(content)


def is_usable_probe_response(status_code: int, content: bytes | str | None, *, min_bytes: int = 100) -> bool:
    if status_code != 200:
        return False
    if content is None:
        return False
    content_length = len(content.encode("utf-8")) if isinstance(content, str) else len(content)
    return content_length > min_bytes and not has_blocked_body(content)
