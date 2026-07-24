"""Agent answer-phase gating tool.

[INPUT]
- langchain_core.tools::tool

[OUTPUT]
- request_answer_user_tool: Static tool instance that triggers the answer phase.

[POS]
Framework-level scheduling signal for the completion_guard middleware.
Agent calls this tool to indicate that a self-review has passed and it is
ready to produce the final answer.  Downstream middlewares (e.g.
tool_selection_middleware) react by setting ``tool_choice="none"`` to force
the model into direct-answer mode.

Zero business dependencies — pure LangChain tool + logging.
"""

import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

ANSWER_USER_TOOL_DESCRIPTION = """
Call only when you can deliver a complete, accurate, up-to-date answer after self-review.

Before calling:
- Coverage: every entity and constraint in the user request is addressed.
- Accuracy: facts are consistent across sources; conflicts are resolved.
- Freshness: time-sensitive facts match the system current time.

If information is incomplete, use web_fetch_tool on the best official or authoritative URLs first.
Do not call twice in one turn, and do not call in parallel with other tools.
After this tool succeeds, produce the final user-facing answer directly.
""".strip()


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


request_answer_user_tool = tool(
    "request_answer_user_tool",
    description=ANSWER_USER_TOOL_DESCRIPTION,
)(_request_answer_user_impl)
