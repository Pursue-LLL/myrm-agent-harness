"""LLM-visible descriptions for memory agent tools (prompt/cache SSOT).

Kept separate from ``memory_agent_tools.py`` so static tests can import
descriptions without pulling MemoryManager or search execution dependencies.

English and Chinese variants are both first-class LLM-facing strings.
Default locale is English; callers pass BCP-47 locale strings (e.g. ``zh-CN``).

[INPUT]
- toolkits.memory.memory_search_policy::MemorySearchPolicy (POS: corpus ACL for memory_search_tool)
- utils.locale::is_chinese (POS: BCP-47 Chinese detection for description locale)

[OUTPUT]
- build_memory_search_tool_description: Dynamic memory_search_tool description builder
- resolve_memory_save_tool_description / resolve_memory_manage_tool_description
- MEMORY_*_TOOL_DESCRIPTION_EN / _ZH: locale-specific SSOT constants

[POS]
Prompt SSOT for memory agent tools. Imported by memory_agent_tools.py and static tests.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.memory_search_policy import MemorySearchPolicy
from myrm_agent_harness.utils.locale import is_chinese

DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE = "en"

# =============================================================================
# English (default LLM-facing)
# =============================================================================

MEMORY_SAVE_TOOL_DESCRIPTION_EN = """Store a new memory for the user. Memory persists across sessions and is injected
into future conversations, so keep entries compact and focused on durable facts.

**WHEN TO SAVE** (do this proactively):
- User explicitly says "remember this", "note this", "don't forget"
- User corrects your behavior or output style
- User shares a stable preference, habit, or personal detail (name, role, timezone)
- You discover something about the user's environment or project that won't change soon
- User sets a rule: "always do X" / "never do Y"

**WHAT NOT TO SAVE**:
- Task progress, session outcomes, completed-work logs (use memory_search with corpus=sessions instead)
- Temporary state: PR numbers, commit SHAs, current file paths, WIP items
- Information that will be stale within a week
- Step-by-step procedures or workflows (not suitable for memory)
- Raw data dumps, code snippets, or lengthy text

**CONTENT QUALITY** — write as declarative facts, not instructions:
- GOOD: "User prefers dark themes" (declarative fact)
- BAD: "Always use dark theme" (instruction-style, gets misinterpreted as a command)
- One fact per memory entry; include enough context to be useful standalone

**ATTRIBUTION & TRANSIENT STATES** (CRITICAL):
- Strictly distinguish the user from third parties (family, friends, colleagues). NEVER attribute a third party's traits, illnesses, or preferences to the user. (e.g., "User's boss prefers dark mode", NOT "User prefers dark mode").
- DO NOT save transient emotional or psychological states (e.g., "User is feeling anxious today") unless explicitly stated as a chronic condition.

**CATEGORY GUIDE**:
- knowledge: stable facts about user's world (project tech stack, environment details)
- event: significant past occurrences worth recalling (user started new project)
- preference: user likes/dislikes (requires preference_key)
- rule: conditional behavioral rules (requires rule_trigger)
- instruction: global instructions that always apply (highest priority)

**IMPORTANCE SCORING**:
- 0.8–1.0: User explicitly asked to remember / correction of your behavior
- 0.5–0.7: Inferred stable preference or environment fact
- 0.2–0.4: Supplementary context, nice-to-have

**WRITE TARGET**:
- "bound" (default): visible only to the current agent persona
- "shared": cross-agent knowledge (user's name, timezone) — use sparingly

Args:
    content: Memory content text — declarative, concise, standalone.
    category: knowledge | event | preference | rule | instruction.
    importance: 0–1 importance score (see scoring guide above).
    tags: Classify this memory with descriptive labels for later filtering
        (e.g. ["python", "auth"], ["cooking", "italian"]). Knowledge/event only.
    write_target: "bound" for current agent; "shared" for cross-agent knowledge.
    preference_key: Required for preference category (e.g. "response_style").
    rule_trigger: Required for rule category (context that triggers the rule).
    rule_priority: Priority for rules (higher = stronger override).
    rule_keywords: Optional trigger keywords for rule activation."""

MEMORY_MANAGE_TOOL_DESCRIPTION_EN = """Update, delete, correct, or rate an existing memory.

**WHEN TO USE**:
- User says "forget that" / "that's wrong" / "remove that memory" → delete or correct
- A recalled memory is outdated or inaccurate → correct (preserves history)
- User confirms a memory is helpful → rate (reinforces retrieval ranking)
- A memory needs minor wording fix → update

Args:
    action: "update", "delete", "correct", or "rate".
    memory_id: Memory ID from memory_search results.
    category: knowledge | event | preference | rule.
    new_content: Required for update/correct actions.
    new_importance: Optional new importance score.
    rating_score: Required for rate action (1-5, where 1=bad, 5=excellent).

The "correct" action is for when a memory is factually wrong.
It demotes the old memory (low confidence) and creates a new
high-confidence correction memory linked to it, so future
retrievals automatically prefer the corrected version.

The "rate" action records user feedback on a memory. Higher-rated
memories are ranked higher in search results and resist forgetting."""

# =============================================================================
# Chinese (LLM-facing; must stay semantically aligned with English)
# =============================================================================

MEMORY_SAVE_TOOL_DESCRIPTION_ZH = """为用户存储新记忆。记忆跨会话持久化并注入未来对话，请保持条目紧凑、聚焦 durable facts。

**何时保存**（应主动执行）：
- 用户明确说「记住这个」「记一下」「别忘了」
- 用户纠正你的行为或输出风格
- 用户分享稳定偏好、习惯或个人细节（姓名、角色、时区）
- 你发现用户环境/项目中短期内不会变的事实
- 用户设定规则：「总是 X」「绝不 Y」

**不要保存**：
- 任务进度、会话结果、已完成工作日志（改用 memory_search，corpus=sessions）
- 临时状态：PR 号、commit SHA、当前文件路径、进行中的事项
- 一周内会过时的信息
- 分步流程或工作流（不适合记忆）
- 原始数据 dump、代码片段或冗长文本

**内容质量** — 写陈述性事实，不要写指令：
- 好："User prefers dark themes"（陈述性事实）
- 差："Always use dark theme"（指令式，易被误解为命令）
- 每条记忆一个事实；包含足够上下文以便独立理解

**归属与 transient states**（关键）：
- 严格区分用户与第三方（家人、朋友、同事）。绝不要把第三方的特质、疾病或偏好归因给用户。（如 "User's boss prefers dark mode"，而非 "User prefers dark mode"）。
- 不要保存 transient 情绪或心理状态（如 "User is feeling anxious today"），除非用户明确为 chronic condition。

**类别指南**：
- knowledge：用户世界的稳定事实（项目技术栈、环境细节）
- event：值得回忆的重要过往事件（用户开始新项目）
- preference：用户喜好/厌恶（需 preference_key）
- rule：条件性行为规则（需 rule_trigger）
- instruction：始终适用的全局指令（最高优先级）

**重要性评分**：
- 0.8–1.0：用户明确要求记住 / 纠正你的行为
- 0.5–0.7：推断的稳定偏好或环境事实
- 0.2–0.4：补充上下文，nice-to-have

**写入目标**：
- "bound"（默认）：仅当前 Agent persona 可见
- "shared"：跨 Agent 知识（用户姓名、时区等）— 谨慎使用

Args:
    content: 记忆正文 — 陈述性、简洁、可独立理解。
    category: knowledge | event | preference | rule | instruction。
    importance: 0–1 重要性分数（见上方评分指南）。
    tags: 描述性标签便于后续过滤（如 ["python", "auth"]）。仅 knowledge/event。
    write_target: "bound" 当前 Agent；"shared" 跨 Agent。
    preference_key: preference 类别必填（如 "response_style"）。
    rule_trigger: rule 类别必填（触发上下文）。
    rule_priority: 规则优先级（越高越强）。
    rule_keywords: 可选触发关键词。"""

MEMORY_MANAGE_TOOL_DESCRIPTION_ZH = """更新、删除、纠正或评分已有记忆。

**何时使用**：
- 用户说「忘了那个」「不对」「删掉那条记忆」→ delete 或 correct
- 召回的记忆过时或不准确 → correct（保留历史）
- 用户确认某条记忆有帮助 → rate（强化检索排序）
- 记忆需要小幅措辞修正 → update

Args:
    action: "update"、"delete"、"correct" 或 "rate"。
    memory_id: memory_search 结果中的 Memory ID。
    category: knowledge | event | preference | rule。
    new_content: update/correct 时必填。
    new_importance: 可选的新重要性分数。
    rating_score: rate 时必填（1-5，1=差，5=优）。

"correct" 用于记忆事实错误时：旧记忆降置信，并创建与之链接的新高置信 correction 记忆，未来检索自动优先新版本。

"rate" 记录用户对记忆的反馈。高分记忆在搜索结果中排序更靠前、更抗遗忘。"""

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
    ]
    if policy.allow_sessions:
        tip_lines.append(
            '- For recent chats without a query, use corpus=sessions with query="*"'
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
    ]
    if policy.allow_sessions:
        tip_lines.append('- 查最近聊天无 query：corpus=sessions，query="*"')
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


def resolve_memory_save_tool_description(
    locale: str | None = DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE,
) -> str:
    if is_chinese(locale):
        return MEMORY_SAVE_TOOL_DESCRIPTION_ZH
    return MEMORY_SAVE_TOOL_DESCRIPTION_EN


def resolve_memory_manage_tool_description(
    locale: str | None = DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE,
) -> str:
    if is_chinese(locale):
        return MEMORY_MANAGE_TOOL_DESCRIPTION_ZH
    return MEMORY_MANAGE_TOOL_DESCRIPTION_EN


__all__ = [
    "DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE",
    "MEMORY_MANAGE_TOOL_DESCRIPTION",
    "MEMORY_MANAGE_TOOL_DESCRIPTION_EN",
    "MEMORY_MANAGE_TOOL_DESCRIPTION_ZH",
    "MEMORY_SAVE_TOOL_DESCRIPTION",
    "MEMORY_SAVE_TOOL_DESCRIPTION_EN",
    "MEMORY_SAVE_TOOL_DESCRIPTION_ZH",
    "build_memory_search_tool_description",
    "resolve_memory_manage_tool_description",
    "resolve_memory_save_tool_description",
]
