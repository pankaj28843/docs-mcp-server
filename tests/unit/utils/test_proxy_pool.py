"""Unit tests for proxy-pool selection and block detection."""

import pytest

from docs_mcp_server.utils.proxy_pool import (
    ProxyPool,
    has_blocked_body,
    is_usable_probe_response,
    normalize_proxy_list,
    proxy_label,
    should_rotate_proxy,
)


@pytest.mark.unit
def test_proxy_pool_sticks_to_success_then_rotates_after_block():
    pool = ProxyPool(["http://a:1", "http://b:2", "http://c:3"])

    assert pool.candidates() == ["http://a:1", "http://b:2", "http://c:3"]

    pool.mark_success("http://b:2")
    assert pool.candidates() == ["http://b:2", "http://c:3", "http://a:1"]

    pool.mark_blocked("http://b:2")
    assert pool.candidates() == ["http://c:3", "http://a:1", "http://b:2"]


@pytest.mark.unit
def test_proxy_pool_uses_direct_only_without_configured_proxies():
    pool = ProxyPool([])

    assert pool.candidates() == [None]
    assert pool.proxies == ()
    assert pool.has_proxies is False
    pool.mark_success(None)
    pool.mark_blocked(None)
    assert proxy_label(None) == "direct"


@pytest.mark.unit
def test_proxy_pool_ignores_empty_duplicates_and_unknown_proxies():
    pool = ProxyPool([" http://a:1 ", "", None, "http://a:1", "http://b:2"])

    assert normalize_proxy_list([" http://a:1 ", "", None, "http://a:1", "http://b:2"]) == [
        "http://a:1",
        "http://b:2",
    ]
    assert pool.proxies == ("http://a:1", "http://b:2")

    pool.mark_success("http://missing:9")
    assert pool.candidates() == ["http://a:1", "http://b:2"]

    pool.mark_blocked("http://missing:9")
    assert pool.candidates() == ["http://a:1", "http://b:2"]


@pytest.mark.unit
def test_block_detection_rejects_google_sorry_pages():
    body = b"<html><title>Sorry</title>google.com/sorry unusual traffic</html>"

    assert has_blocked_body(body) is True
    assert should_rotate_proxy(200, body) is True
    assert is_usable_probe_response(200, body) is False


@pytest.mark.unit
def test_probe_requires_200_non_blocked_content():
    assert is_usable_probe_response(200, b"x" * 200) is True
    assert is_usable_probe_response(200, "x" * 200) is True
    assert is_usable_probe_response(200, None) is False
    assert is_usable_probe_response(429, b"x" * 200) is False
    assert should_rotate_proxy(503, b"service unavailable") is True
