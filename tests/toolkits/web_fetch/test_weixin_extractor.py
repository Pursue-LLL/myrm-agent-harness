"""Unit tests for WeChat Official Account article extractor."""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.toolkits.web_fetch.extractors import (
    weixin_extractor as weixin_extractor_module,
)
from myrm_agent_harness.toolkits.web_fetch.extractors.weixin_extractor import (
    extract_weixin_article,
    get_weixin_request_headers,
    has_weixin_js_content,
    is_weixin_article_url,
    parse_weixin_article_html,
)

_SAMPLE_HTML = """
<html>
<head>
<meta property="og:title" content="从 ReAct Agent 到 Harness Agent：构建可自举的 AI Agent" />
<meta name="description" content="认识Harness Agent，手搓 Harness Agent" />
</head>
<body>
<h1 id="activity-name">从 ReAct Agent 到 Harness Agent：构建可自举的 AI Agent</h1>
<em id="publish_time">2026-03-01</em>
<a id="js_name">AI开发者日记</a>
<div id="js_content">
<p>Agent 的概念从 23 年就已经很火了，一开始主流就是 ReAct Agent。</p>
<p>Harness Agent 并没有对认知模型进行替换，是在它之上做了更多的限制性工作。</p>
<p>这就是 Claude Code 和 Codex 的核心引擎的微缩版，足够覆盖读取代码到运行验证的完整闭环。</p>
<img data-src="https://mmbiz.qpic.cn/sample-cover.jpg" src="data:image/gif;base64,R0lGODlh" />
</div>
</body>
</html>
"""

_META_ONLY_HTML = """
<html>
<head>
<meta property="og:title" content="Meta Title Fallback" />
<meta property="og:article:author" content="Meta Author" />
<meta property="og:article:published_time" content="2026-02-02T08:00:00+08:00" />
<meta name="description" content="Meta description body" />
</head>
<body>
<div id="js_content">
<p>这是一篇通过 meta 标签补全作者和发布时间的微信公众号文章正文，长度足够通过最小正文字数校验。</p>
<p>第二段补充说明 Harness Agent 读取链路的单元测试覆盖场景与边界条件。</p>
</div>
</body>
</html>
"""

_SCRIPT_TIME_HTML = """
<html><body><div id="js_content">
<p>脚本发布时间提取测试正文，内容长度超过最小阈值以便 parse 成功并写入 Document metadata 字段。</p>
<p>第二段继续补充 Harness Agent 读取链路的单元测试覆盖场景与边界条件说明。</p>
<script>var createTime = '2026-04-04';</script>
</div></body></html>
"""

_BLOCKED_HTML = """
<html><body><h2>环境异常</h2><p>完成验证后即可继续访问。</p></body></html>
"""

_QUERY_URL = "https://mp.weixin.qq.com/s?__biz=Mzg2NzY0MTkzOQ==&mid=2247493844&idx=1"
_ARTICLE_URL = "https://mp.weixin.qq.com/s/D6PTZsG3DgbEOB11vvQQMA"


def test_is_weixin_article_url_matches_short_and_query_links() -> None:
    assert is_weixin_article_url(_ARTICLE_URL)
    assert is_weixin_article_url(_QUERY_URL)
    assert is_weixin_article_url("https://mp.weixin.qq.com/s/abc?chksm=foo")
    assert is_weixin_article_url("https://sub.mp.weixin.qq.com/s/abc")
    assert not is_weixin_article_url("https://example.com/s/foo")
    assert not is_weixin_article_url("https://mp.weixin.qq.com/mp/homepage")
    assert not is_weixin_article_url("ftp://mp.weixin.qq.com/s/abc")


def test_get_weixin_request_headers() -> None:
    headers = get_weixin_request_headers("mp.weixin.qq.com")
    assert "MicroMessenger" in headers["User-Agent"]
    assert headers["Referer"] == "https://mp.weixin.qq.com/"
    assert get_weixin_request_headers("sub.mp.weixin.qq.com")["User-Agent"]
    assert get_weixin_request_headers("example.com") == {}


def test_has_weixin_js_content() -> None:
    assert has_weixin_js_content('<div id="js_content">')
    assert has_weixin_js_content("<div id='js_content'>")
    assert not has_weixin_js_content("<div id='other'>")


def test_parse_weixin_article_html_extracts_title_author_publish_time_images_and_body() -> (
    None
):
    doc = parse_weixin_article_html(_SAMPLE_HTML, url=_ARTICLE_URL)
    assert doc is not None
    assert (
        doc.metadata["title"]
        == "从 ReAct Agent 到 Harness Agent：构建可自举的 AI Agent"
    )
    assert doc.metadata["author"] == "AI开发者日记"
    assert doc.metadata["publish_time"] == "2026-03-01"
    assert doc.metadata["source_type"] == "weixin_article"
    assert "ReAct Agent" in doc.page_content
    assert "Harness Agent" in doc.page_content
    assert "https://mmbiz.qpic.cn/sample-cover.jpg" in doc.page_content
    image_urls = json.loads(doc.metadata["image_urls"])
    assert "https://mmbiz.qpic.cn/sample-cover.jpg" in image_urls


def test_parse_weixin_article_html_uses_meta_fallbacks() -> None:
    doc = parse_weixin_article_html(_META_ONLY_HTML, url=_ARTICLE_URL)
    assert doc is not None
    assert doc.metadata["title"] == "Meta Title Fallback"
    assert doc.metadata["author"] == "Meta Author"
    assert doc.metadata["publish_time"] == "2026-02-02T08:00:00+08:00"


def test_parse_weixin_article_html_reads_publish_time_from_script() -> None:
    doc = parse_weixin_article_html(_SCRIPT_TIME_HTML, url=_ARTICLE_URL)
    assert doc is not None
    assert doc.metadata["publish_time"] == "2026-04-04"


def test_parse_weixin_article_html_rejects_verification_page() -> None:
    assert (
        parse_weixin_article_html(
            _BLOCKED_HTML, url="https://mp.weixin.qq.com/s/blocked"
        )
        is None
    )


def test_parse_weixin_article_html_rejects_missing_js_content() -> None:
    html = "<html><body><p>no article container</p></body></html>"
    assert parse_weixin_article_html(html, url=_ARTICLE_URL) is None


def test_parse_weixin_article_html_rejects_short_body() -> None:
    html = '<html><body><div id="js_content"><p>too short</p></div></body></html>'
    assert parse_weixin_article_html(html, url=_ARTICLE_URL) is None


def test_parse_weixin_article_html_truncates_overlong_body() -> None:
    long_paragraph = "长" * 25_000
    html = (
        f'<html><body><div id="js_content"><p>{long_paragraph}</p></div></body></html>'
    )
    doc = parse_weixin_article_html(html, url=_ARTICLE_URL)
    assert doc is not None
    assert "body truncated" in doc.page_content


def test_parse_skips_duplicate_and_non_http_images() -> None:
    html = """
    <html><body><div id="js_content">
    <p>图片去重与非 HTTP 资源过滤测试正文，长度超过最小阈值以便 parse 成功返回 Document。</p>
    <img data-src="https://mmbiz.qpic.cn/a.jpg" />
    <img data-src="https://mmbiz.qpic.cn/a.jpg" />
    <img data-src="/local/path.jpg" />
    <img src="https://mmbiz.qpic.cn/b.jpg" />
    </div></body></html>
    """
    doc = parse_weixin_article_html(html, url=_ARTICLE_URL)
    assert doc is not None
    image_urls = json.loads(doc.metadata["image_urls"])
    assert image_urls == ["https://mmbiz.qpic.cn/a.jpg", "https://mmbiz.qpic.cn/b.jpg"]


@pytest.mark.asyncio
async def test_extract_weixin_article_returns_none_for_non_weixin_url() -> None:
    assert await extract_weixin_article("https://example.com/article") is None


@pytest.mark.asyncio
async def test_extract_weixin_article_fetches_and_parses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        weixin_extractor_module,
        "_fetch_html",
        lambda url, opener: _SAMPLE_HTML,
    )
    doc = await extract_weixin_article(_ARTICLE_URL)
    assert doc is not None
    assert doc.metadata["title"]


@pytest.mark.asyncio
async def test_extract_weixin_article_retries_after_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []

    def flaky_fetch(url: str, opener: object) -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("temporary network failure")
        return _SAMPLE_HTML

    monkeypatch.setattr(weixin_extractor_module, "_fetch_html", flaky_fetch)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    doc = await extract_weixin_article(_ARTICLE_URL, max_attempts=2)
    assert doc is not None
    assert len(attempts) == 2


def test_fetch_html_decodes_response_and_caps_size() -> None:
    class _Headers:
        def get_content_charset(self, default: str = "utf-8") -> str:
            return default

    class _FakeResponse:
        headers = _Headers()

        def read(self, max_bytes: int) -> bytes:
            return b"hello"

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class _FakeOpener:
        def open(self, req: object, timeout: float) -> _FakeResponse:
            return _FakeResponse()

    result = weixin_extractor_module._fetch_html(_ARTICLE_URL, _FakeOpener())
    assert result == "hello"


def test_build_opener_blocks_redirects() -> None:
    import urllib.error
    import urllib.request

    handler = weixin_extractor_module._NoRedirectHandler()
    req = urllib.request.Request(_ARTICLE_URL)  # noqa: S310
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example/")


def _html_with_images(n: int) -> str:
    imgs = "\n".join(
        f'<img data-src="https://img.example.com/{i}.png" />' for i in range(n)
    )
    return f'<html><body><div id="js_content"><h1>标题</h1><p>{"正文内容" * 40}</p>{imgs}</div></body></html>'


def test_normalize_lazy_images_handles_list_attr() -> None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        "<div id='js_content'><img data-src='https://a.com/x.png' /></div>",
        "html.parser",
    )
    img = soup.find("img")
    assert img is not None
    img.attrs["data-src"] = ["https://a.com/x.png"]
    div = soup.find("div")
    assert div is not None
    weixin_extractor_module._normalize_lazy_images(div)
    assert img.get("src") == "https://a.com/x.png"


def test_collect_image_urls_caps_at_max_images() -> None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_html_with_images(35), "html.parser")
    div = soup.find(id="js_content")
    assert div is not None
    urls = weixin_extractor_module._collect_image_urls(div)
    assert len(urls) == weixin_extractor_module._MAX_IMAGES


def test_collect_image_urls_handles_list_src() -> None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_html_with_images(1), "html.parser")
    img = soup.find("img")
    assert img is not None
    img.attrs["data-src"] = ["https://img.example.com/1.png"]
    div = soup.find(id="js_content")
    assert div is not None
    urls = weixin_extractor_module._collect_image_urls(div)
    assert urls == ["https://img.example.com/1.png"]


def test_parse_rejects_js_content_only_inside_script() -> None:
    html = (
        "<html><body><script>const tpl = '<div id=\"js_content\"></div>';</script>"
        "<p>正文内容" * 60 + "</p></body></html>"
    )
    assert parse_weixin_article_html(html, url=_ARTICLE_URL) is None


def test_build_opener_with_proxy_pool() -> None:
    class _Proxy:
        def to_url(self) -> str:
            return "http://proxy.example:8080"

    class _Pool:
        def get_next(self) -> _Proxy:
            return _Proxy()

    opener = weixin_extractor_module._build_opener(_Pool())
    assert opener is not None


def test_fetch_html_caps_oversized_response() -> None:
    class _Headers:
        def get_content_charset(self, default: str = "utf-8") -> str:
            return default

    cap = weixin_extractor_module._MAX_RESPONSE_BYTES

    class _FakeResponse:
        headers = _Headers()

        def read(self, max_bytes: int) -> bytes:
            return b"x" * (cap + 100)

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class _FakeOpener:
        def open(self, req: object, timeout: float) -> _FakeResponse:
            return _FakeResponse()

    result = weixin_extractor_module._fetch_html(_ARTICLE_URL, _FakeOpener())
    assert len(result) == cap


@pytest.mark.asyncio
async def test_extract_rejects_non_http_scheme() -> None:
    assert await extract_weixin_article("ftp://mp.weixin.qq.com/s/abc123") is None


@pytest.mark.asyncio
async def test_extract_scheme_guard_defense_in_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even when the URL classifier is bypassed, non-http(s) schemes are refused."""

    monkeypatch.setattr(
        weixin_extractor_module, "is_weixin_article_url", lambda url: True
    )
    assert await extract_weixin_article("ftp://mp.weixin.qq.com/s/abc123") is None


@pytest.mark.asyncio
async def test_extract_all_attempts_fail_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        weixin_extractor_module,
        "_fetch_html",
        lambda url, opener: None,
    )
    doc = await extract_weixin_article(_ARTICLE_URL, max_attempts=2)
    assert doc is None


@pytest.mark.asyncio
async def test_extract_all_attempts_raise_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_fetch(url: str, opener: object) -> str:
        raise ConnectionError("all attempts dead")

    monkeypatch.setattr(weixin_extractor_module, "_fetch_html", failing_fetch)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    doc = await extract_weixin_article(_ARTICLE_URL, max_attempts=2)
    assert doc is None
