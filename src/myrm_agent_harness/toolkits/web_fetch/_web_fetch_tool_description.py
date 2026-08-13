"""web_fetch_tool LLM-visible description (prompt/cache SSOT).

Kept separate from ``web_fetch_agent_tools.py`` so static tests can import
without pulling fetch engine dependencies.

English and Chinese variants are both first-class LLM-facing strings.
Default locale is English; callers pass BCP-47 locale strings (e.g. ``zh-CN``).

[INPUT]
- utils.locale::is_chinese (POS: BCP-47 Chinese detection for description locale)

[OUTPUT]
- resolve_web_fetch_tool_description: Locale-aware description resolver
- WEB_FETCH_TOOL_DESCRIPTION_EN / _ZH: locale-specific SSOT constants

[POS]
Prompt SSOT for web_fetch_tool. Imported by web_fetch_agent_tools.py and static tests.
"""

from __future__ import annotations

from myrm_agent_harness.utils.locale import is_chinese

DEFAULT_WEB_FETCH_TOOL_DESCRIPTION_LOCALE = "en"

_EXTRACT_SECTION_EN = """
### fetch_and_extract

Retrieve **relevant content snippets** from known webpages (single or multiple URLs).

**Use cases:**
- Retrieve relevant info from webpages that can answer user questions; use this operation in most cases

**Parameters:**
- urls: Known and real target webpage URL list, no fabrication allowed
- questions: Query list, must be rewritten according to "query rewriting rules"
- operation: "fetch_and_extract"

**Query rewriting rules:**
- Generate 1-5 queries centered on user intent
- **Language alignment**: Query language should match target webpage language when possible
"""

_FULL_CONTENT_WITH_EXTRACT_EN = """
### fetch_full_content

Get the **full content** of known webpages (single or multiple URLs).

**Use cases:**
- User explicitly requests full page content
- Need to summarize or analyze the entire webpage

**Parameters:**
- urls: Known webpage URL list
- operation: "fetch_full_content"
"""

_FULL_CONTENT_ONLY_EN = """
Get full content from known webpage URLs (Markdown format). Supports single or multiple URLs.

**Parameters:**
- urls: Known and real target webpage URL list, no fabrication allowed
- operation: "fetch_full_content"
"""

_HEADER_EN = """web_fetch_tool extracts detailed content from specific webpage URLs.
{sections}
For read-only content retrieval (articles, docs, blog posts), always prefer this tool over browser_navigate — it's faster, cheaper, and handles JS rendering internally.
WeChat Official Account article links (mp.weixin.qq.com/s/...) are supported via fetch_full_content; use the real article URL the user provided.
For JS-heavy or interactive pages (clicking, filling forms, scrolling), use browser tools. For many pages, call web_fetch with multiple URLs."""

_EXTRACT_SECTION_ZH = """
### fetch_and_extract

从已知网页（单个或多个 URL）中检索**相关内容片段**。

**适用场景：**
- 从能够回答用户问题的网页中检索相关信息；大多数情况使用此操作

**参数：**
- urls：已知且真实的目标网页 URL 列表，禁止编造
- questions：查询列表，必须按「query 改写规则」改写
- operation："fetch_and_extract"

**Query 改写规则：**
- 围绕用户意图生成 1-5 条查询
- **语言对齐**：查询语言应尽量与目标网页语言一致
"""

_FULL_CONTENT_WITH_EXTRACT_ZH = """
### fetch_full_content

获取已知网页（单个或多个 URL）的**完整内容**。

**适用场景：**
- 用户明确要求获取完整页面内容
- 需要总结或分析整个网页

**参数：**
- urls：已知网页 URL 列表
- operation："fetch_full_content"
"""

_FULL_CONTENT_ONLY_ZH = """
从已知网页 URL 获取完整内容（Markdown 格式）。支持单个或多个 URL。

**参数：**
- urls：已知且真实的目标网页 URL 列表，禁止编造
- operation："fetch_full_content"
"""

_HEADER_ZH = """web_fetch_tool 从指定的网页 URL 提取详细内容。
{sections}
对于只读内容检索（文章、文档、博客），始终优先使用本工具而非 browser_navigate——更快、更省，内部处理 JS 渲染。
微信公众号文章链接（mp.weixin.qq.com/s/...）可通过 fetch_full_content 获取；使用用户提供的真实文章 URL。
对于 JS 重或交互式页面（点击、填表、滚动），请使用浏览器工具。页面较多时，可在一次调用中传入多个 URL。"""


def resolve_web_fetch_tool_description(
    enable_extract: bool, locale: str | None = DEFAULT_WEB_FETCH_TOOL_DESCRIPTION_LOCALE
) -> str:
    """Return the locale-aware tool description for the configured fetch mode.

    ``enable_extract`` mirrors the tool's runtime capability: when the reranker
    and embedding services are available, ``fetch_and_extract`` is offered and
    the description documents both operations; otherwise only
    ``fetch_full_content`` is described so the LLM never attempts a disabled
    operation.
    """
    if is_chinese(locale):
        if enable_extract:
            sections = _EXTRACT_SECTION_ZH + _FULL_CONTENT_WITH_EXTRACT_ZH
        else:
            sections = _FULL_CONTENT_ONLY_ZH
        return _HEADER_ZH.format(sections=sections).strip()

    if enable_extract:
        sections = _EXTRACT_SECTION_EN + _FULL_CONTENT_WITH_EXTRACT_EN
    else:
        sections = _FULL_CONTENT_ONLY_EN
    return _HEADER_EN.format(sections=sections).strip()


__all__ = [
    "DEFAULT_WEB_FETCH_TOOL_DESCRIPTION_LOCALE",
    "resolve_web_fetch_tool_description",
]
