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
Call only when you can deliver a complete, accurate, up-to-date answer after self-review.

Before calling:
- Coverage: every entity and constraint in the user request is addressed.
- Accuracy: facts are consistent across sources; conflicts are resolved.
- Freshness: time-sensitive facts match the system current time.

If information is incomplete, use web_fetch_tool on the best official or authoritative URLs first.
Do not call twice in one turn, and do not call in parallel with other tools.
After this tool succeeds, produce the final user-facing answer directly.
""".strip()

ANSWER_USER_TOOL_DESCRIPTION_ZH: Final[str] = """
仅在完成自我审查并确认能够交付完整、准确、最新答案时调用。

调用前自查：
- 覆盖度：用户请求中的每个实体与约束均已解决。
- 准确度：多方事实一致；冲突已消除。
- 时效性：时效事实与系统当前时间匹配。

若信息不完整，优先使用 web_fetch_tool 查阅最佳官方或权威 URL。
单轮内切勿重复调用，切勿与其他工具并行调用。
本工具成功后，直接向用户输出最终答案。
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
