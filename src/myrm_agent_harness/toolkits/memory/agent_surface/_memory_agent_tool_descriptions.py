"""LLM-visible descriptions for memory agent tools (prompt/cache SSOT).

Kept separate from ``memory_agent_tools.py`` so static tests can import
descriptions without pulling MemoryManager or search execution dependencies.

English and Chinese variants are both first-class LLM-facing strings.
Default locale is English; callers pass BCP-47 locale strings (e.g. ``zh-CN``).

[INPUT]
- toolkits.memory.agent_surface.memory_search_policy::MemorySearchPolicy (POS: corpus ACL for memory_search_tool)
- utils.locale::is_chinese (POS: BCP-47 Chinese detection for description locale)

[OUTPUT]
- build_memory_search_tool_description: Dynamic memory_search_tool description builder
- build_memory_save_tool_description: Dynamic memory_save_tool description (policy + approval)
- resolve_memory_save_tool_description / resolve_memory_manage_tool_description
- MEMORY_SAVE_CORE_* / MEMORY_*_TOOL_DESCRIPTION_EN / _ZH: locale-specific SSOT constants

[POS]
Prompt SSOT for memory agent tools. Imported by memory_agent_tools.py, mcp_server.py (memory_manage/memory_store with surface=mcp), and static tests.
"""

from __future__ import annotations

from typing import Literal

from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
    MemorySearchPolicy,
)
from myrm_agent_harness.toolkits.memory.agent_surface.wiki_memory_boundary import (
    WIKI_MEMORY_SAVE_MAX_CHARS,
    WIKI_MEMORY_SAVE_MIN_HEADINGS,
)
from myrm_agent_harness.utils.locale import is_chinese

DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE = "en"

MemoryToolDescriptionSurface = Literal["agent", "mcp"]

_AGENT_TO_MCP_TOOL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("memory_manage_tool", "memory_manage"),
    ("memory_search_tool", "memory_recall"),
    ("memory_save_tool", "memory_store"),
)

_MCP_SURFACE_EXTRA_REPLACEMENTS_EN: tuple[tuple[str, str], ...] = (
    (
        "Task progress, session outcomes, or completed-work logs → use memory_recall with corpus=sessions",
        "Task progress, session outcomes, or completed-work logs → do not store via memory_store",
    ),
    (
        "Task progress or chat history → memory_recall with corpus=sessions",
        "Task progress or chat history → do not use memory_manage for session logs",
    ),
    (
        "- Use wiki_ingest_tool for articles, notes, or long reference text. Memory is for short durable facts.",
        "- Long-form articles, notes, or reference text are not appropriate for memory. "
        "Memory is for short durable facts.",
    ),
)

_MCP_SURFACE_EXTRA_REPLACEMENTS_ZH: tuple[tuple[str, str], ...] = (
    (
        "任务进度、会话结果、已完成工作日志 → 使用 memory_recall，corpus=sessions",
        "任务进度、会话结果、已完成工作日志 → 不要用 memory_store 存储",
    ),
    (
        "任务进度或聊天历史 → memory_recall，corpus=sessions",
        "任务进度或聊天历史 → 不要用 memory_manage 管理会话日志",
    ),
    (
        "- 长文/笔记/参考资料请用 wiki_ingest_tool；memory 只存短小的持久事实。",
        "- 长文/笔记/参考资料不属于 memory；memory 只存短小的持久事实。",
    ),
)


def _apply_tool_surface_names(
    description: str,
    *,
    surface: MemoryToolDescriptionSurface = "agent",
    locale: str | None = DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE,
) -> str:
    """Map GUI Turn1 tool names to MCP HTTP tool names when surface is mcp."""
    if surface == "agent":
        return description
    result = description
    for agent_name, mcp_name in _AGENT_TO_MCP_TOOL_REPLACEMENTS:
        result = result.replace(agent_name, mcp_name)
    extras = (
        _MCP_SURFACE_EXTRA_REPLACEMENTS_ZH
        if is_chinese(locale)
        else _MCP_SURFACE_EXTRA_REPLACEMENTS_EN
    )
    for old, new in extras:
        result = result.replace(old, new)
    return result


# =============================================================================
# English (default LLM-facing)
# =============================================================================

MEMORY_SAVE_CORE_EN = """Store a new memory for the user. Memory persists across sessions and is injected into future conversations, so keep entries compact and focused on durable facts: one standalone declarative fact per entry.

**WHEN TO SAVE** (do this proactively):
- User explicitly says "remember this", "note this", "don't forget"
- User corrects your behavior or output style (agent conduct — not a stored fact correction; see below)
- User shares a stable preference, habit, or personal detail (name, role, timezone)
- You discover something about the user's environment or project that won't change soon
- User sets a rule: "always do X" / "never do Y"

**WHEN NOT TO USE THIS TOOL**:
- An existing recalled memory fact is wrong → use memory_manage_tool with action=correct (do not save a duplicate)
- Task progress, session outcomes, or completed-work logs → use memory_search_tool with corpus=sessions
- Temporary state: PR numbers, commit SHAs, current file paths, WIP items
- Information that will be stale within a week
- Step-by-step procedures or workflows (not suitable for memory)
- Raw data dumps, code snippets, or lengthy text
- Do not retry identical content if the tool reports a duplicate

**CONTENT QUALITY** — write as declarative facts, not instructions:
- GOOD: "User prefers dark themes" (declarative fact)
- BAD: "Always use dark theme" (instruction-style, gets misinterpreted as a command)
- One fact per memory entry; include enough context to be useful standalone

**ATTRIBUTION & TRANSIENT STATES** (CRITICAL):
- Strictly distinguish the user from third parties (family, friends, colleagues). NEVER attribute a third party's traits, illnesses, or preferences to the user (e.g., "User's boss prefers dark mode", NOT "User prefers dark mode").
- DO NOT save transient emotional or psychological states (e.g., "User is feeling anxious today") unless explicitly stated as a chronic condition.

**CATEGORY GUIDE** (pick one):
- knowledge: stable facts about user's world (project tech stack, environment details) — tags and importance apply here
- event: significant past occurrences worth recalling (e.g., user started new project) — do not specify importance or tags for events
- preference: user likes/dislikes (requires preference_key)
- rule: conditional behavioral rules with a specific condition (requires rule_trigger, e.g., "when writing code"; optional rule_priority, rule_keywords)
- instruction: unconditional global rules that always apply (e.g., "always reply in Chinese") — do not set rule_trigger

**IMPORTANCE SCORING** (0–1, primarily for knowledge):
- 0.8–1.0: User explicitly asked to remember / correction of your behavior
- 0.5–0.7: Inferred stable preference or environment fact
- 0.2–0.4: Supplementary context, nice-to-have

**WRITE TARGET**:
- "bound" (default): visible only to the current agent persona
- "shared": cross-agent knowledge (user's name, timezone) — use sparingly

Parameter semantics are in the tool schema."""

MEMORY_SAVE_TOOL_DESCRIPTION_EN = MEMORY_SAVE_CORE_EN

MEMORY_MANAGE_TOOL_DESCRIPTION_EN = """Update, delete, correct, or rate an existing memory from memory_search_tool results.

**WHEN TO USE** (not memory_save_tool):
- User says "forget that", "that's wrong", or "remove that memory"
- A recalled memory is outdated or inaccurate → correct
- A memory needs minor wording fix → update
- User confirms a memory was helpful → rate (reinforces retrieval ranking)

**WHEN NOT TO USE**:
- Storing new facts, preferences, or rules → memory_save_tool
- Task progress or chat history → memory_search_tool with corpus=sessions

**ACTION GUIDE**:
- delete: remove a memory (pinned memories cannot be deleted by the agent)
- update: fix wording or importance only — not for wrong facts; requires new_content
- correct: fix a wrong recalled fact — knowledge category only; requires new_content; preserves history; use instead of memory_save_tool when correcting existing memories
- rate: record user feedback — knowledge or event only; requires rating_score 1-5 (1=poor, 5=excellent)

**CATEGORY LIMITS**:
- correct → knowledge only
- rate → knowledge or event only
- preference profile attributes cannot be deleted via this tool
- instruction saves (via memory_save_tool) are stored as rules with trigger "always"; manage them with category=rule

Parameter semantics are in the tool schema."""

# =============================================================================
# Chinese (LLM-facing; must stay semantically aligned with English)
# =============================================================================

MEMORY_SAVE_CORE_ZH = """为用户存储新记忆。记忆跨会话持久化并注入未来对话，请保持条目紧凑、聚焦持久事实：一条可独立理解的陈述性事实。

**何时保存**（应主动执行）：
- 用户明确说「记住这个」「记一下」「别忘了」
- 用户纠正你的行为或输出风格（指 Agent 行为，不是已存事实纠错；见下方）
- 用户分享稳定偏好、习惯或个人细节（姓名、角色、时区）
- 你发现用户环境/项目中短期内不会变的事实
- 用户设定规则：「总是 X」「绝不 Y」

**何时禁止使用本工具（转用其他工具/机制）**：
- 已召回的记忆事实有误 → 使用 memory_manage_tool，action=correct（不要重复 save）
- 任务进度、会话结果、已完成工作日志 → 使用 memory_search_tool，corpus=sessions
- 临时状态：PR 号、commit SHA、当前文件路径、进行中的事项
- 一周内会过时的信息
- 分步流程或工作流（不适合记忆）
- 原始数据转储、代码片段或冗长文本
- 若工具返回重复提示，不要用相同内容重试

**内容质量** — 写陈述性事实，不要写指令：
- 好："User prefers dark themes"（陈述性事实）
- 差："Always use dark theme"（指令式，易被误解为命令）
- 每条记忆一个事实；包含足够上下文以便独立理解

**归属与短暂状态**（关键）：
- 严格区分用户与第三方（家人、朋友、同事）。绝不要把第三方的特质、疾病或偏好归因给用户（如 "User's boss prefers dark mode"，而非 "User prefers dark mode"）。
- 不要保存短暂情绪或心理状态（如 "User is feeling anxious today"），除非用户明确说明是长期或慢性状况。

**类别指南**（择一）：
- knowledge：用户世界的稳定事实（项目技术栈、环境细节）— 标签与重要性适用于此类
- event：值得回忆的重要过往事件（如用户开始新项目）— event 无需指定 importance 与 tags
- preference：用户喜好/厌恶（需 preference_key）
- rule：包含具体触发条件的条件性行为规则（需 rule_trigger，如「写代码时」；可选 rule_priority、rule_keywords）
- instruction：始终适用的无条件全局指令（如「始终用中文回复」）— 不要设置 rule_trigger

**重要性评分**（0–1，主要用于 knowledge）：
- 0.8–1.0：用户明确要求记住 / 纠正你的行为
- 0.5–0.7：推断的稳定偏好或环境事实
- 0.2–0.4：补充上下文，可有可无

**写入目标**：
- "bound"（默认）：仅当前 Agent 角色可见
- "shared"：跨 Agent 知识（用户姓名、时区等）— 谨慎使用

参数说明见工具参数定义。"""

MEMORY_SAVE_TOOL_DESCRIPTION_ZH = MEMORY_SAVE_CORE_ZH

MEMORY_MANAGE_TOOL_DESCRIPTION_ZH = """更新、删除、纠正或评分已有记忆（memory_id 来自 memory_search_tool 结果）。

**何时使用**（不要用 memory_save_tool）：
- 用户说「忘了那个」「不对」「删掉那条记忆」
- 召回的记忆过时或不准确 → correct
- 记忆需要小幅措辞修正 → update
- 用户确认某条记忆有帮助 → rate（强化检索排序）

**不要改用本工具的情况**：
- 存储新事实、偏好或规则 → memory_save_tool
- 任务进度或聊天历史 → memory_search_tool，corpus=sessions

**操作指南**：
- delete：删除记忆（已钉选的记忆 Agent 不能删）
- update：仅改措辞或重要性 — 不用于事实错误；需要 new_content
- correct：纠正错误的已召回事实 — 仅 knowledge 类别；需要 new_content；保留历史记录；纠正已有记忆时优先于 memory_save_tool
- rate：记录用户反馈 — 仅 knowledge 或 event；需要 rating_score 1-5（1=差，5=优）

**类别限制**：
- correct → 仅 knowledge
- rate → 仅 knowledge 或 event
- preference 类 profile 属性不能通过本工具删除
- instruction 保存（memory_save_tool）后存为 trigger=always 的 rule；管理时用 category=rule

参数说明见工具参数定义。"""

# Default aliases (English)
MEMORY_SAVE_TOOL_DESCRIPTION = MEMORY_SAVE_TOOL_DESCRIPTION_EN
MEMORY_MANAGE_TOOL_DESCRIPTION = MEMORY_MANAGE_TOOL_DESCRIPTION_EN


def _join_scope_fragments(fragments: list[str]) -> str:
    if not fragments:
        return ""
    if len(fragments) == 1:
        return fragments[0]
    if len(fragments) == 2:
        return f"{fragments[0]} and {fragments[1]}"
    return ", ".join(fragments[:-1]) + f", and {fragments[-1]}"


def _build_memory_search_en(policy: MemorySearchPolicy) -> str:
    scope_fragments = ["long-term memory"]
    if policy.allow_wiki:
        scope_fragments.append("wiki")
    if policy.allow_sessions:
        scope_fragments.append("prior conversations")
    if policy.allow_web:
        scope_fragments.append("web corpus")

    corpus_lines = [
        "- memory (default): durable facts, preferences, profile, learned rules",
    ]
    if policy.allow_sessions:
        corpus_lines.append("- sessions: prior chat snippets and summaries")
    if policy.allow_wiki:
        corpus_lines.append("- wiki: agent wiki vault content")
    if policy.allow_web:
        corpus_lines.append("- web: previously fetched/searched web pages")
    corpus_lines.append("- all: search every corpus enabled for this agent")

    tip_lines = [
        '- Be specific: "user\'s Python framework preference" not just "Python"',
        "- Filter categories for memory corpus: knowledge, claim, event, preference, rule",
        "- Use profile_key for instant attribute lookup (memory corpus only)",
        "- Use since/until for time-scoped queries (7d, 2w, 1m, 24h, 1y, or ISO 8601)",
        "- For memory retrieval only.",
    ]
    if policy.allow_sessions:
        tip_lines.append(
            '- For recent chats without a query, use corpus=sessions with query="*"'
        )
        tip_lines.append(
            "- When a sessions hit includes message_id and the user needs verbatim detail, "
            "call again with corpus=sessions, expand_conversation_id, and expand_message_id"
        )
    if policy.allow_web:
        tip_lines.append(
            "- Use corpus=web to re-query pages you've already searched or fetched"
        )

    context_parts = ["personal context", "preferences"]
    if policy.allow_wiki:
        context_parts.append("wiki docs")
    if policy.allow_web:
        context_parts.append("previously fetched web pages")
    if policy.allow_sessions:
        context_parts.append("earlier chat evidence")

    return (
        f"Unified search across {_join_scope_fragments(scope_fragments)}.\n\n"
        f"Use when the user's question relates to {_join_scope_fragments(context_parts)}.\n\n"
        "**Corpus guide**:\n"
        + "\n".join(corpus_lines)
        + "\n\n**Search tips**:\n"
        + "\n".join(tip_lines)
    )


def _build_memory_search_zh(policy: MemorySearchPolicy) -> str:
    scope_fragments = ["长期记忆"]
    if policy.allow_wiki:
        scope_fragments.append("Wiki")
    if policy.allow_sessions:
        scope_fragments.append("历史会话")
    if policy.allow_web:
        scope_fragments.append("web corpus")

    corpus_lines = [
        "- memory（默认）：持久事实、偏好、profile、已学规则",
    ]
    if policy.allow_sessions:
        corpus_lines.append("- sessions：历史聊天片段与摘要")
    if policy.allow_wiki:
        corpus_lines.append("- wiki：Agent Wiki vault")
    if policy.allow_web:
        corpus_lines.append("- web：已抓取/搜索过的网页")
    corpus_lines.append("- all：搜索当前 Agent 启用的全部 corpus")

    tip_lines = [
        "- 要具体：「user's Python framework preference」而非仅「Python」",
        "- memory corpus 过滤类别：knowledge、claim、event、preference、rule",
        "- profile_key 可即时查属性（仅 memory corpus）",
        "- since/until 时间范围：7d、2w、1m、24h、1y 或 ISO 8601",
        "- 仅用于记忆检索。",
    ]
    if policy.allow_sessions:
        tip_lines.append('- 查最近聊天无 query：corpus=sessions，query="*"')
        tip_lines.append(
            "- sessions 结果含 message_id 且用户要原文细节时，用 corpus=sessions 并传 expand_conversation_id 与 expand_message_id 再查"
        )
    if policy.allow_web:
        tip_lines.append("- corpus=web 可重查已搜索/抓取过的页面")

    context_parts = ["个人上下文", "偏好"]
    if policy.allow_wiki:
        context_parts.append("Wiki 文档")
    if policy.allow_web:
        context_parts.append("已抓取网页")
    if policy.allow_sessions:
        context_parts.append("早期聊天证据")

    zh_join = "、".join(scope_fragments[:-1]) + (
        f"与{scope_fragments[-1]}" if len(scope_fragments) > 1 else scope_fragments[0]
    )
    context_join = "、".join(context_parts)

    return (
        f"跨{zh_join}的统一检索。\n\n"
        f"当用户问题涉及{context_join}时使用。\n\n"
        "**Corpus 指南**：\n"
        + "\n".join(corpus_lines)
        + "\n\n**搜索技巧**：\n"
        + "\n".join(tip_lines)
    )


def build_memory_search_tool_description(
    policy: MemorySearchPolicy,
    *,
    locale: str | None = DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE,
) -> str:
    """Build memory_search_tool description (corpus ACL varies by policy)."""
    if is_chinese(locale):
        return _build_memory_search_zh(policy)
    return _build_memory_search_en(policy)


def _wiki_boundary_fragment_en() -> str:
    return (
        f"**WIKI BOUNDARY** (wiki corpus enabled):\n"
        f"- For knowledge/event only: do not save document-like content "
        f"(≥{WIKI_MEMORY_SAVE_MAX_CHARS} characters or ≥{WIKI_MEMORY_SAVE_MIN_HEADINGS} markdown headings).\n"
        "- Use wiki_ingest_tool for articles, notes, or long reference text. "
        "Memory is for short durable facts."
    )


def _wiki_boundary_fragment_zh() -> str:
    return (
        f"**Wiki 边界**（已启用 wiki corpus）：\n"
        f"- 仅 knowledge/event：不要保存文档式内容"
        f"（≥{WIKI_MEMORY_SAVE_MAX_CHARS} 字符或 ≥{WIKI_MEMORY_SAVE_MIN_HEADINGS} 个 markdown 标题）。\n"
        "- 长文/笔记/参考资料请用 wiki_ingest_tool；memory 只存短小的持久事实。"
    )


def _approval_fragment_en() -> str:
    return (
        "**APPROVAL**: When user confirmation is required, the tool may return "
        '"submitted for approval" — the memory is not active until the user approves.'
    )


def _approval_fragment_zh() -> str:
    return "**审批**：若需用户确认，工具可能返回「submitted for approval」——在用户批准前该记忆不会生效。"


def build_memory_save_tool_description(
    policy: MemorySearchPolicy,
    *,
    approval_required: bool = False,
    locale: str | None = DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE,
    surface: MemoryToolDescriptionSurface = "agent",
) -> str:
    """Build memory_save_tool description (wiki boundary + approval vary by runtime)."""
    parts: list[str] = [
        MEMORY_SAVE_CORE_ZH if is_chinese(locale) else MEMORY_SAVE_CORE_EN
    ]
    if policy.allow_wiki:
        parts.append(
            _wiki_boundary_fragment_zh()
            if is_chinese(locale)
            else _wiki_boundary_fragment_en()
        )
    if approval_required:
        parts.append(
            _approval_fragment_zh() if is_chinese(locale) else _approval_fragment_en()
        )
    return _apply_tool_surface_names("\n\n".join(parts), surface=surface, locale=locale)


def build_mcp_memory_store_tool_description(
    *,
    wiki_boundary_in_description: bool = False,
    approval_required: bool = False,
    locale: str | None = DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE,
) -> str:
    """Build memory_store MCP @tool description from save SSOT core.

    The wiki boundary fragment is excluded by default: the MCP surface exposes
    no wiki tools, and the runtime wiki guard is enabled per-request by the
    server (ContextVar), so a static "(wiki corpus enabled)" claim would be
    false for most connected agents. Callers that manage their own per-agent
    wiki enablement may opt in via ``wiki_boundary_in_description``.
    """
    policy = MemorySearchPolicy(allow_wiki=wiki_boundary_in_description)
    return build_memory_save_tool_description(
        policy,
        approval_required=approval_required,
        locale=locale,
        surface="mcp",
    )


def resolve_memory_save_tool_description(
    locale: str | None = DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE,
    *,
    surface: MemoryToolDescriptionSurface = "agent",
) -> str:
    return build_memory_save_tool_description(
        MemorySearchPolicy(),
        locale=locale,
        surface=surface,
    )


def resolve_memory_manage_tool_description(
    locale: str | None = DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE,
    *,
    surface: MemoryToolDescriptionSurface = "agent",
) -> str:
    base = (
        MEMORY_MANAGE_TOOL_DESCRIPTION_ZH
        if is_chinese(locale)
        else MEMORY_MANAGE_TOOL_DESCRIPTION_EN
    )
    return _apply_tool_surface_names(base, surface=surface, locale=locale)


__all__ = [
    "DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE",
    "MEMORY_MANAGE_TOOL_DESCRIPTION",
    "MEMORY_MANAGE_TOOL_DESCRIPTION_EN",
    "MEMORY_MANAGE_TOOL_DESCRIPTION_ZH",
    "MEMORY_SAVE_CORE_EN",
    "MEMORY_SAVE_CORE_ZH",
    "MEMORY_SAVE_TOOL_DESCRIPTION",
    "MEMORY_SAVE_TOOL_DESCRIPTION_EN",
    "MEMORY_SAVE_TOOL_DESCRIPTION_ZH",
    "MemoryToolDescriptionSurface",
    "build_mcp_memory_store_tool_description",
    "build_memory_save_tool_description",
    "build_memory_search_tool_description",
    "resolve_memory_manage_tool_description",
    "resolve_memory_save_tool_description",
]
