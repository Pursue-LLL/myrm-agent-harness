"""Agent answer-phase gating tool.

[INPUT]
- langchain_core.tools::tool
- utils.locale::is_chinese (POS: BCP-47 Chinese detection for description locale)

[OUTPUT]
- create_answer_user_tool: Factory function creating answer_user_tool with locale support
- request_answer_user_tool: Static tool instance that triggers the answer phase (default English)

[POS]
Framework-level scheduling signal for the completion_guard middleware.
Agent calls this tool to indicate that a self-review has passed and it is
ready to produce the final answer.  Downstream middlewares (e.g.
tool_selection_middleware) react by setting ``tool_choice="none"`` to force
the model into direct-answer mode.

Zero business dependencies — pure LangChain tool + logging.
"""

import logging
from typing import Final

from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.utils.locale import is_chinese

logger = logging.getLogger(__name__)

ANSWER_USER_TOOL_DESCRIPTION_EN: Final[str] = """
Call only when you can confidently deliver a complete, accurate, up-to-date answer after self-review.

## Self-Review Standards (All must be satisfied):
1. Absolute Completeness:
- Single-fact queries: The exact core fact (e.g. date, location, verified figure) is confirmed.
- Exhaustive / list / multi-step queries: Must include full list and all steps. Truncated snippets, summaries, key highlights, or partial lists NEVER equal a complete answer. Never deliver truncated info.
2. Absolute Accuracy:
- Facts are consistent across sources; resolve conflicting claims logically using authoritative primary sources.
3. Absolute Freshness:
- Strictly calibrate against system current time. Never rely on relative tenses in search results (e.g. "upcoming", "recent", "currently").

## Actions When Incomplete:
1. Deep-dive clues: If information is incomplete, identify high-value URL clues from search results:
   - Primary sources: official documentation, changelogs, release notes, authoritative publishers.
   - Entity match: title or snippet clearly indicates the core target entity.
   - Suggestive URL paths: domain or path strongly implies complete content.
   Filter 1-N most useful, non-duplicate, highly specific URLs, and use web_fetch_tool to extract complete details.
2. Adjust strategy: Refine parameters or use alternative tools if needed.

## Rules & Invariants:
- Single call per turn: Do not call twice in one turn, and do not call in parallel with other tools.
- Deliver answer immediately: Proceed directly to output the final user-facing answer after this tool succeeds.
""".strip()

ANSWER_USER_TOOL_DESCRIPTION_ZH: Final[str] = """
仅在当你可以自信地提供完美的满分答案时调用此工具来请求回答用户，调用后表示自审通过，可以回答。

## 满分答案自审标准（全部满足，不能妥协，否则不能回答）：
1. 绝对完整：
- 单一事实类：确切核心事实（如时间、地点、特定数据等）已确证无误。
- 穷尽/列表/步骤类：必须包含完整列表与所有步骤。搜索摘要中的「部分高光、主要特性、截断要点」绝不等于完整列表，被截断或缩略的信息绝不能作为满分答案。
2. 绝对准确：
- 事实无争议，且多个来源之间无冲突，或已通过逻辑/官方一手权威来源解决冲突。
3. 绝对时效：
- 始终以系统提供的当前时间为唯一判断基准，严禁依赖搜索结果原文时态（如「实时」、「当前」、「即将」等时态要根据系统当前时间重新判断）。

## 如何得到满分答案？
1. 深挖线索：如果目前信息无法提供满分答案，但是有高价值网页线索时，你可以使用 web_fetch_tool 工具深挖线索：
   - 高价值线索识别：
     * 来源是官方文档、发布说明（Changelog/Release Notes）、权威一手来源。
     * 标题/摘要明确标注了用户查询的核心实体（版本号、事件名等）。
     * 域名或 URL 路径强烈暗示其包含完整答案（即使摘要很短）。
   - 筛选出 1-N 个最有用的、不重复的、最具体的高质量 URL，使用 web_fetch_tool 从目标网站中深挖能够回答用户问题的完整信息。
2. 调整方案：寻找其他有效方案，如调整参数或使用其他工具或技能等。

## 调用约束与原则：
- 用户体验优先：不要提供低质量答案，信息不足或质量低时，必须深挖线索或调整方案。
- 单次调用：每次对话回合中只应调用一次。禁止重复调用或在并行工具调用中多次包含此工具。
- 即时输出：本工具成功后，直接向用户输出最终答案。
""".strip()

ANSWER_USER_TOOL_DESCRIPTION = ANSWER_USER_TOOL_DESCRIPTION_EN


def resolve_answer_user_tool_description(locale: str | None = None) -> str:
    """Resolve LLM-facing request_answer_user_tool description."""
    if is_chinese(locale):
        return ANSWER_USER_TOOL_DESCRIPTION_ZH
    return ANSWER_USER_TOOL_DESCRIPTION_EN


def _request_answer_user_impl(
    reason: str = "Information is complete; ready to answer the user.",
    **_extra: object,
) -> str:
    """Trigger the answer phase.

    The middleware reacts by setting ``tool_choice="none"`` and prompting
    the model to produce a direct user-facing answer.
    """
    logger.info("[request_answer_user_tool] reason=%s", reason)
    return "Ready to answer user"


def create_answer_user_tool(locale: str | None = None) -> BaseTool:
    """Create a localized instance of request_answer_user_tool."""
    return tool(
        "request_answer_user_tool",
        description=resolve_answer_user_tool_description(locale),
    )(_request_answer_user_impl)


# Backward-compatible static instance
request_answer_user_tool = create_answer_user_tool()

__all__ = [
    "ANSWER_USER_TOOL_DESCRIPTION",
    "ANSWER_USER_TOOL_DESCRIPTION_EN",
    "ANSWER_USER_TOOL_DESCRIPTION_ZH",
    "create_answer_user_tool",
    "request_answer_user_tool",
    "resolve_answer_user_tool_description",
]
