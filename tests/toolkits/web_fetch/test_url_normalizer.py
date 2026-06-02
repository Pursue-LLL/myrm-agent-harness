"""测试 URL 规范化功能"""

import pytest

from myrm_agent_harness.toolkits.web_fetch.url_normalizer import normalize_url


def test_remove_tracking_params():
    """测试移除追踪参数"""
    url = "https://example.com/page?utm_source=google&utm_medium=cpc&id=123"
    normalized = normalize_url(url)
    assert "utm_source" not in normalized
    assert "utm_medium" not in normalized
    assert "id=123" in normalized


def test_remove_extended_tracking_params():
    """测试移除扩展的追踪参数（HubSpot, LinkedIn, TikTok 等）"""
    test_cases = [
        ("https://example.com?_hsenc=abc&_hsmi=123&id=1", "id=1"),
        ("https://example.com?li_fat_id=xyz&li_source=test&id=2", "id=2"),
        ("https://example.com?ttclid=tiktok&twclid=twitter&id=3", "id=3"),
        ("https://example.com?s_cid=adobe&_gid=ga&id=4", "id=4"),
        ("https://example.com?fbclid=fb&gclid=google&msclkid=bing&id=5", "id=5"),
    ]

    for url, expected_param in test_cases:
        normalized = normalize_url(url)
        assert expected_param in normalized
        assert "hsenc" not in normalized
        assert "li_fat_id" not in normalized
        assert "ttclid" not in normalized
        assert "s_cid" not in normalized


def test_lowercase_scheme_and_netloc():
    """测试统一 scheme 和 netloc 为小写"""
    url = "HTTPS://EXAMPLE.COM/Page"
    normalized = normalize_url(url)
    assert normalized.startswith("https://example.com/")


def test_remove_default_ports():
    """测试移除默认端口"""
    assert normalize_url("http://example.com:80/page") == "http://example.com/page"
    assert normalize_url("https://example.com:443/page") == "https://example.com/page"
    assert normalize_url("http://example.com:8080/page") == "http://example.com:8080/page"


def test_normalize_path():
    """测试规范化路径（移除多余斜杠）"""
    url = "https://example.com//path//to///page"
    normalized = normalize_url(url)
    assert "/path/to/page" in normalized


def test_sort_query_params():
    """测试查询参数按字母排序"""
    url = "https://example.com/page?z=3&a=1&m=2"
    normalized = normalize_url(url)
    assert normalized == "https://example.com/page?a=1&m=2&z=3"


def test_complex_url():
    """测试复杂 URL 规范化"""
    url = "HTTPS://Example.COM:443//path//to/page?utm_source=fb&z=3&a=1&fbclid=xyz"
    normalized = normalize_url(url)

    assert normalized.startswith("https://example.com/")
    assert "utm_source" not in normalized
    assert "fbclid" not in normalized
    assert "a=1" in normalized
    assert "z=3" in normalized
    assert normalized.index("a=1") < normalized.index("z=3")


def test_url_without_query():
    """测试没有查询参数的 URL"""
    url = "https://example.com/page"
    normalized = normalize_url(url)
    assert normalized == "https://example.com/page"


def test_url_with_fragment():
    """测试带 fragment 的 URL（fragment 不应该被保留）"""
    url = "https://example.com/page#section"
    normalized = normalize_url(url)
    assert "#section" not in normalized


@pytest.mark.parametrize(
    "url1,url2",
    [
        ("https://example.com/page?utm_source=a", "https://example.com/page"),
        ("HTTPS://EXAMPLE.COM/page", "https://example.com/page"),
        ("https://example.com:443/page", "https://example.com/page"),
        ("https://example.com/page?z=1&a=2", "https://example.com/page?a=2&z=1"),
    ],
)
def test_equivalent_urls_normalized_to_same(url1: str, url2: str):
    """测试等价 URL 规范化为相同结果"""
    assert normalize_url(url1) == normalize_url(url2)
