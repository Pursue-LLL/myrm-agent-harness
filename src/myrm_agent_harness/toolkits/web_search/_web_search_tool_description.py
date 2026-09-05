"""web_search_tool LLM-visible description (prompt/cache SSOT).

Kept separate from ``web_search_agent_tools.py`` so static tests can import
without pulling search engine dependencies.

English and Chinese variants are both first-class LLM-facing strings.
Default locale is English; callers pass BCP-47 locale strings (e.g. ``zh-CN``).

[INPUT]
- utils.locale::is_chinese (POS: BCP-47 Chinese detection for description locale)

[OUTPUT]
- resolve_web_search_tool_description: Locale-aware description resolver
- WEB_SEARCH_TOOL_DESCRIPTION_EN / _ZH: locale-specific SSOT constants

[POS]
Prompt SSOT for web_search_tool. Imported by web_search_agent_tools.py and static tests.
"""

from __future__ import annotations

from myrm_agent_harness.utils.locale import is_chinese

DEFAULT_WEB_SEARCH_TOOL_DESCRIPTION_LOCALE = "en"

WEB_SEARCH_TOOL_DESCRIPTION_EN = """
Use web_search_tool to retrieve real-time information from the internet, including news, academic material, and specific facts. Use when information is time-sensitive, the user requests an online search, or you cannot reliably verify facts. Do not call when you can answer reliably without going online.

## Parameters

- questions: 1-5 search queries per call. Batch searches in one call are allowed; more queries cost more.
- reason: One brief sentence stating the search purpose. Do not repeat the user's question.
- time_range: Set only when the user explicitly gives a time range or relative time requirement (day/week/month/year or YYYY-MM-DD..YYYY-MM-DD).
- When the user wants official or authoritative sources, use site: in the query to restrict domains (e.g. site:gov.cn, site:github.com). Do not rely on other parameters for this.

## Optimal cost control

- For most questions, generate 1-2 queries; for complex or multi-faceted questions only, generate 3-5 queries, at most 5.
- Each query must include the entities, keywords, and constraints needed to retrieve the answer; avoid irrelevant words. One call should cover the core information dimensions of the user's question; unless key information is missing, do not repeat similar searches.
- If results do not cover key aspects needed to answer, prefer rewriting for missing aspects or adding complementary queries.

## Query rewrite rules

Generate queries in the following order:

1. Determine true intent

- Using the user's question and conversation history, identify core entities, the problem to solve, and explicit constraints.
- Version, date, location, language, locale, scope, and exclusion conditions must be preserved; do not change them arbitrarily.
- When the user states an unverified premise, queries must stay neutral to verify that premise; do not rewrite it as established fact.

2. Complete context

- First decide whether the current question is a follow-up. If it contains referential or elliptical expressions such as "it", "that", "he/she", "what about...", or "how about...", resolve the referent from conversation history and replace the pronoun.
- Each query must be understandable on its own, outside the conversation and other queries, with complete independently searchable information; never rely on another query to supply missing meaning.
- Expand abbreviations, codes, or short names that appear alone without context.
- For domain-specific structured identifiers (such as CVE-YYYY-NNNN, DOI 10.xxxx/..., stock/quote tickers), preserve the exact identifier intact in the query rather than diluting it with generic descriptions.
- Example: history "What are the new features in Python 3.12?"; current "How does it compare to 3.11?" → `Python 3.12 vs Python 3.11 new features comparison`.

3. Correction and normalization

- Fix obvious spelling, grammar, or terminology errors using standard names and expressions that search engines recognize easily.
- Correct only confirmed errors; do not use correction to change user intent, entities, or constraints.
- Example: when the contextual entity is Next.js 15, "Why is it so slow?" → `Next.js 15 performance issues causes`.

4. Disambiguation and recency

- For ambiguous expressions, prefer conversation history to disambiguate. When sufficiently justified, choose one most likely mainstream entity or event; never include mutually conflicting entities, years, or constraints at once.
- If multiple interpretations are reasonable and would materially change the answer, do not guess or fabricate; ask the user to clarify first.
- For time-sensitive information such as news, prices, events, schedules, or versions, add "today", "latest", or a concrete date consistent with the current date when needed; never invent years, versions, or events.

5. Aggregation and decomposition

- For simple questions, prefer one complete query.
- For complex questions, generate a specific query for each independent sub-question; within the limit of at most 5 queries, a complex question may additionally include one synthesis query.
- A synthesis query seeks high-quality material that broadly covers multiple sub-questions; it supplements specific queries and must not replace them.

6. Multi-dimension coverage and deduplication

- Do not produce synonymous rewrites or overlapping information. If results for query A would usually already answer query B, query B is redundant.
- When generating multiple queries, cover complementary information dimensions relevant to user intent. Applicable angles include: [results/predictions], [comparison/decision], [causes/depth], [how-to/pitfalls]; do not generate queries the user does not need just to fill dimensions.
- When asking about a process or schedule, you may add logically matching results, outcomes, or ranking queries; add them only when they help answer the user's question.
- Do not mismatch dimensions: do not generate tutorial queries such as "how to organize S15" when the user asks for "S15 schedule".
- Bad example: `S15 schedule`, `S15 schedule arrangement`, `S15 timetable`, `S15 start time` — they all search the same time dimension.
""".strip()

WEB_SEARCH_TOOL_DESCRIPTION_ZH = """
web_search_tool 用于检索互联网中的实时信息、新闻、学术资料和具体事实。当信息具有时效性、用户要求联网查询，或模型无法可靠确认事实时，应使用本工具。无需联网且能够可靠回答时不要调用。

## 参数

- questions：1-5 条搜索 query。单次调用可批量搜索；query 越多，成本越高。
- reason：用一句简短的话说明搜索目的，不要复述用户问题。
- time_range：仅当用户明确给出时间范围或相对时间要求时设置（day/week/month/year 或 YYYY-MM-DD..YYYY-MM-DD）。
- 用户要求官方或权威来源时，在 query 中使用 site: 限定域名（如 site:gov.cn、site:github.com），不要依赖其他参数。

## 最优成本控制

- 大多数问题生成 1-2 条 query；仅复杂或多方面问题生成 3-5 条，最多 5 条。
- 每条 query 应包含检索答案所需的实体、关键词和约束，避免无关词语。一次调用尽量覆盖用户问题的核心信息维度；除非缺少关键信息，不要重复搜索相似内容。
- 若结果没有覆盖回答所需的关键方面，优先改写缺失方面或增加互补 query。

## Query 改写规则

按以下顺序生成 query：

1. 确定真实意图

- 结合用户问题与会话历史，识别核心实体、用户要解决的问题及明确约束。
- 版本、日期、地点、语言、地区、范围和排除条件必须保留，不得擅自更改。
- 用户提出未经证实的前提时，query 应保持中性，用于核实该前提，不得将其改写成既定事实。

2. 补全上下文

- 先判断当前问题是否为跟进问题。若包含「它、那个、他、那……呢、怎么样」等指代或省略表达，须从会话历史确定所指实体并替换代词。
- 每条 query 脱离会话和其他 query 后都必须可理解，包含完整、可独立检索的信息；禁止依赖另一条 query 补足语义。
- 补全单独出现且没有上下文的缩写、代号或短名称。
- 涉及专业领域结构化标识符（如 CVE-YYYY-NNNN 漏洞号、DOI 10.xxxx/... 论文号、股票行情代码等）时，务必在 query 中完整保留原始标识符，不要稀释为模糊泛化表述。
- 示例：历史「Python 3.12 有什么新特性？」；当前「和 3.11 比怎么样？」→ `Python 3.12 与 Python 3.11 新特性对比`。

3. 纠错与标准化

- 修正明显的拼写、语法或术语错误，使用搜索引擎容易识别的标准名称和表达。
- 仅修正确认无误的错误；不得借纠错改变用户意图、实体或约束。
- 示例：上下文实体为 Next.js 15 时，「为什么这么慢？」→ `Next.js 15 性能问题原因`。

4. 消歧与时效性

- 对模糊表达，优先利用会话历史消歧。有充分依据时，采用一个最可能的主流实体或事件；不得同时补入互相冲突的实体、年份或约束。
- 若多个解释都合理且会显著影响答案，不得猜测或编造，应先请求用户澄清。
- 对新闻、价格、赛事、赛程、版本等时效性信息，必要时在 query 中加入与当前日期一致的「今日」「最新」或具体日期；不得虚构年份、版本或事件。

5. 聚合与分解

- 简单问题优先使用一条完整 query。
- 对复杂问题，为独立子问题生成具体 query；在最多 5 条的限制内，复杂问题可额外加入一条综合 query。
- 综合 query 用于寻找全面覆盖多个子问题的高质量资料，是对具体 query 的补充，不能替代具体 query。

6. 多维度与去重

- 禁止同义改写或信息重叠。若 query A 的结果通常已能回答 query B，query B 即为冗余。
- 生成多条 query 时，必须覆盖互补且与用户意图相关的信息维度。可选择适用角度：[赛果/预测]、[对比/决策]、[原因/深度]、[做法/踩坑]；不得为凑维度生成用户不需要的 query。
- 查询过程或赛程时，可补充逻辑匹配的结果、赛果或排名 query；仅在有助于回答用户问题时添加。
- 禁止维度错配：不要为「S15 赛程」生成「如何组织 S15」等教程 query。
- 错误示例：`S15 赛程`、`S15 赛程安排`、`S15 时间表`、`S15 何时开始` — 它们都在搜索同一时间维度。
""".strip()

WEB_SEARCH_TOOL_DESCRIPTION = WEB_SEARCH_TOOL_DESCRIPTION_EN


def resolve_web_search_tool_description(
    locale: str | None = DEFAULT_WEB_SEARCH_TOOL_DESCRIPTION_LOCALE,
) -> str:
    if is_chinese(locale):
        return WEB_SEARCH_TOOL_DESCRIPTION_ZH
    return WEB_SEARCH_TOOL_DESCRIPTION_EN


__all__ = [
    "DEFAULT_WEB_SEARCH_TOOL_DESCRIPTION_LOCALE",
    "WEB_SEARCH_TOOL_DESCRIPTION",
    "WEB_SEARCH_TOOL_DESCRIPTION_EN",
    "WEB_SEARCH_TOOL_DESCRIPTION_ZH",
    "resolve_web_search_tool_description",
]
