"""Prompt descriptions for ask_question HITL clarification tool.

[INPUT]
- utils.locale::is_chinese (POS: BCP-47 Chinese detection for description locale)

[OUTPUT]
- ASK_QUESTION_TOOL_DESCRIPTION_EN: English description for ask_question_tool.
- ASK_QUESTION_TOOL_DESCRIPTION_ZH: Chinese description for ask_question_tool.
- resolve_ask_question_tool_description(): Locale-aware resolver.

[POS]
SSOT for LLM-facing ask_question_tool prompt descriptions.
Ensures adherence to tool prompt guidelines (clarity, constraints, high adherence for weaker models).
"""

from __future__ import annotations

from typing import Final

from myrm_agent_harness.utils.locale import is_chinese

ASK_QUESTION_TOOL_DESCRIPTION_EN: Final[str] = """
Ask the user one or more structured clarifying questions when blocked on genuine ambiguity, decisions, or missing prerequisites.

When to use:
- The user request has multiple valid interpretations or critical missing parameters.
- Architectural decisions or trade-offs require user direction.
- You need confirmation before destructive, irreversible, or high-risk operations (set requires_confirmation=true).

Best practices for question quality:
- Do NOT ask questions for information you can easily verify yourself using file search or web search tools.
- When presenting discrete choices, ALWAYS provide structured `options` (at least 2 options with clear `label` and `description`). Put your recommended choice first and suffix its label with "(Recommended)".
- For interpersonal/casual conversational signals (e.g., "let's grab coffee sometime", "ping me when free"), NEVER automatically create work todos. You MUST use this tool to ask for explicit confirmation before promoting interpersonal signals into actionable work items.
- For presentation/PPT reporting tasks, enforce a Plan Outline Quality Gate: ensure slide headlines are active thesis statements (conclusions) rather than static topic labels, and clarify presentation narrative structure before execution.
- Leave `options` empty ONLY for purely open-ended input.
- Set `allow_multiple=true` if the user may select more than one option.

CRITICAL CONSTRAINTS:
- You can only call this tool ONCE per turn.
- If you have multiple questions, put ALL of them in the `questions` list of a SINGLE tool call.
- Do NOT call this tool multiple times in parallel or alongside any other tools in the same turn.
""".strip()

ASK_QUESTION_TOOL_DESCRIPTION_ZH: Final[str] = """
当遇到真正的不确定性、关键方案决策或缺失前置必要信息而受阻时，向用户发起结构化澄清提问。

适用场景：
- 用户请求存在多种合理实现方案、歧义或缺少关键参数。
- 架构设计、技术选型或关键权衡需要用户做出决策。
- 执行破坏性、不可逆或高风险操作前需要用户明确确认（请设置 requires_confirmation=true）。

提问规范与效果保障：
- 禁止反问可以通过文件读取或检索工具自行查证的信息。
- 遇到离散选项时，务必提供结构化 `options`（至少包含 2 个带清晰 `label` 与 `description` 的选项）；将推荐选项置于第一项并在其 label 结尾标注“（推荐）”。
- 遇到社交/非正式闲聊或人际沟通中的弱意向信号时（如“改天一起吃个饭”、“有空聊聊项目”等），严禁擅自自动创建待办；必须通过本工具向用户发起意向晋升确认（“检测到人际交流信号，是否需要转为正式工作待办？”），由用户自主决策。
- 遇到演示汇报/PPT 生成等结构化交付物规划时，严格执行汇报大纲质量门禁（Plan Outline Quality Gate）：确保每页标题采用具备论点表达力与明确结论的观点句（禁止使用“概况”、“总结”等无结论静态话题标签），并在动手前向用户确认故事线与叙事骨架。
- 仅在纯开放式文本收集时才将 `options` 留空。
- 允许用户多选时将 `allow_multiple` 设为 true。

硬性调用约束：
- 单轮对话内【绝对禁止】多次调用本工具。
- 如有多个问题，必须全部放入单次调用的 `questions` 列表中。
- 严禁与其他工具并行调用，本工具必须是该轮唯一的 tool_call。
""".strip()

ASK_QUESTION_TOOL_DESCRIPTION: Final[str] = ASK_QUESTION_TOOL_DESCRIPTION_EN


def resolve_ask_question_tool_description(locale: str | None = None) -> str:
    """Resolve LLM-facing ask_question_tool description based on locale."""
    if is_chinese(locale):
        return ASK_QUESTION_TOOL_DESCRIPTION_ZH
    return ASK_QUESTION_TOOL_DESCRIPTION_EN
