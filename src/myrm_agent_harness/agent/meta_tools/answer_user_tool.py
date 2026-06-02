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
仅在当你可以自信地提供完美的满分答案时调用此工具来请求回答用户，调用后表示自审通过，可以回答。

## **满分答案自审标准（全部满足，不能妥协，否则不能回答）**：

###  **绝对完整**：已收集的信息覆盖了用户问题的每一个核心实体和细节要求。
如何判断是否完整？需根据用户意图分类判断：
- **单一事实类**：如"北京草莓音乐节举办时间？"、"法国首都是哪里？"。用户只关心某个单一具体维度，如时间或地点等。只要"当前可用的信息"中包含该**确切事实**（如"2020-12-02"、"巴黎"），即视为**绝对完整**。
- **穷尽/列表类**：如"Python 3.13新特性？"、"某菜品制作方法？"、"某比赛赛程？"。需要完整的信息、列表或步骤。"当前可用的信息"中**必须**包含"**完整列表/所有步骤**"，只含"关键信息"、"亮点"、"部分列表"、"主要特性"等**永远不等于**"完整列表"，被截断的信息或缩略的信息绝不能作为满分答案。

###  **绝对准确**：事实无争议，且多个来源之间无冲突，或已通过逻辑解决冲突。

###  **绝对时效**：信息没有过时，符合当前日期和时间基准（例如版本号、新闻事件、最新价格等）。
- 始终以系统提供的【当前时间】为唯一判断基准，严禁依赖搜索结果原文时态。原文当时的"实时"、"当前"、"即将"等时态要根据当前时间重新判断。
- 对于实时动态数据如"今天的天气？"、"比特币价格？"、"某股票现价？"等，如果误差超过1小时则不算满分答案。

## 如何得到满分答案？

1. **深挖线索**：如果目前信息无法提供满分答案，但是有高价值网页线索时，你可以使用web_fetch_tool工具深挖线索：
    * **高价值线索识别**：
        * 来源是官方文档、发布说明、权威来源。
        * 标题/摘要明确标注了用户查询的核心实体（版本号、事件名等）。
        * 域名或URL路径强烈暗示其包含完整答案（即使摘要很短）。
    * 你可以筛选出来 1-N 个**最有用的、不重复的、最具体、对回答问题有极大帮助**的高质量URL。然后使用web_fetch_tool工具从目标网站中深挖能够回答用户问题的有用信息。
    * 重复或相似内容时选择更好的一个URL深挖，避免浪费资源
2. **调整方案**：寻找其他有效方案，如调整参数或使用其他工具或技能等。

## 原则

1. **用户体验优先**：不要提供低质量答案，信息不足或质量低时，必须深挖线索或调整方案。
2. request_answer_user_tool 仅在可最终回答时使用，不能提供完美答案时禁止使用。

## 调用约束

1. **单次调用**：每次对话回合中只应调用一次。禁止重复调用或在并行工具调用中多次包含此工具。
2. **信息收集优先**：必须先完成所有信息收集和数据处理，确认满足满分标准后，再调用此工具。
"""


def _request_answer_user_impl(
    reason: str = "信息已完整，请求回答用户",
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
