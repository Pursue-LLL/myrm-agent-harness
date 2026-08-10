"""Unit tests for WeChat Official Account article extractor."""

from __future__ import annotations

import json

from myrm_agent_harness.toolkits.web_fetch.weixin_extractor import (
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

_BLOCKED_HTML = """
<html><body><h2>环境异常</h2><p>完成验证后即可继续访问。</p></body></html>
"""

_QUERY_URL = "https://mp.weixin.qq.com/s?__biz=Mzg2NzY0MTkzOQ==&mid=2247493844&idx=1"


def test_is_weixin_article_url_matches_short_and_query_links() -> None:
    assert is_weixin_article_url("https://mp.weixin.qq.com/s/D6PTZsG3DgbEOB11vvQQMA")
    assert is_weixin_article_url(_QUERY_URL)
    assert is_weixin_article_url("https://mp.weixin.qq.com/s/abc?chksm=foo")
    assert not is_weixin_article_url("https://example.com/s/foo")
    assert not is_weixin_article_url("https://mp.weixin.qq.com/mp/homepage")


def test_parse_weixin_article_html_extracts_title_author_publish_time_images_and_body() -> None:
    doc = parse_weixin_article_html(
        _SAMPLE_HTML,
        url="https://mp.weixin.qq.com/s/D6PTZsG3DgbEOB11vvQQMA",
    )
    assert doc is not None
    assert doc.metadata["title"] == "从 ReAct Agent 到 Harness Agent：构建可自举的 AI Agent"
    assert doc.metadata["author"] == "AI开发者日记"
    assert doc.metadata["publish_time"] == "2026-03-01"
    assert doc.metadata["source_type"] == "weixin_article"
    assert "ReAct Agent" in doc.page_content
    assert "Harness Agent" in doc.page_content
    assert "https://mmbiz.qpic.cn/sample-cover.jpg" in doc.page_content
    image_urls = json.loads(doc.metadata["image_urls"])
    assert "https://mmbiz.qpic.cn/sample-cover.jpg" in image_urls


def test_parse_weixin_article_html_rejects_verification_page() -> None:
    assert parse_weixin_article_html(_BLOCKED_HTML, url="https://mp.weixin.qq.com/s/blocked") is None
