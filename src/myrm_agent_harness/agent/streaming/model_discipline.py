"""Per-model execution discipline — model-aware behavior guidance for the agent.

Resolves model-family-specific execution discipline prompts that steer LLMs
toward better tool usage, reduce hallucination, and correct known failure modes.

Architecture:
    Layer 1: AGENT_CORE_RULES — anti-narration + tool honesty + anti-negative-claim
             + XML tool-call defense + context-first check (all models)
    Layer 2: TOOL_ENFORCEMENT — "must act, not describe" (models with tools)
    Layer 3: MODEL_FAMILY_DISCIPLINE — per-family corrections
             GPT/Codex/Grok  → tool persistence, mandatory tool use, act-don't-ask
             Gemini/Gemma    → absolute paths, parallel calls, non-interactive
             Claude          → execute when instructed, reduce disclaimers
             DeepSeek/Qwen/GLM → reduce over-explanation, enforce tool calls
    Layer 4: ESCALATION_CONTRACT — conditional model self-upgrade contract
             Only injected when escalation_target_llm differs from current model.
             Guides the model to emit <<<NEEDS_PRO>>> when tasks exceed its tier.

All output is fixed text (determined at init time), fully KV-Cache-safe.

See: agent/context_management/PROMPT_CACHE_PRACTICE.md §2.2

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: LangChain chat model base class)

[OUTPUT]
- AGENT_CORE_RULES: base behavior rules constant (anti-narration + tool honesty + anti-negative-claim + XML defense + context-first)
- resolve_execution_discipline(): model-aware discipline resolver (Layer 1-3)
- resolve_escalation_contract(): conditional escalation contract resolver (Layer 4)

[POS]
Per-model execution discipline and escalation contract. Provides model-family-aware
prompt guidance to correct known LLM failure modes, plus conditional self-upgrade
contract when an escalation target model is configured.

"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

# ============================================================================
# Layer 1: Core Agent Rules (all models, always injected)
# ============================================================================

AGENT_CORE_RULES = (
    "\n<agent_behavior_rules>"
    "NEVER narrate or announce tool usage in text. "
    'Do NOT say "让我查一下…", "I will use…", "搜索中…", or similar. '
    "Tool calls are invisible infrastructure — give the FINAL ANSWER directly."
    " NEVER fabricate or guess tool results. "
    'Empty results → say "No results found." '
    "Failures → report the error, never make up data."
    " Before asserting absence — Negative claims ('X is missing', 'there is no Z') — "
    "use a verification tool to confirm. "
    "If the tool returns nothing, state the absence WITH the tool name and "
    "query as evidence (e.g. \"No callers of foo() found (grep 'foo')\"). "
    "If no verification tool is available, qualify: "
    '"I have not verified this — it may be inaccurate."'
    " Use ONLY the native Function Calling API. "
    "NEVER output <tool_call> or similar XML tags in response text."
    " Before calling any tool, check if the answer is already in the "
    "conversation context. Avoid redundant tool calls for information already present."
    "</agent_behavior_rules>"
)

# ============================================================================
# Layer 2: Tool-Use Enforcement (models with available tools)
# ============================================================================

_TOOL_ENFORCEMENT = (
    "\n<tool_use_enforcement>"
    "You MUST use your tools to take action — do not describe what you would do "
    "or plan to do without actually doing it. When you say you will perform an "
    "action (e.g. 'I will run the tests', 'Let me check the file'), you MUST "
    "immediately make the corresponding tool call in the same response. "
    "Never end your turn with a promise of future action — execute it now.\n"
    "Keep working until the task is actually complete. Do not stop with a summary "
    "of what you plan to do next time. If you have tools available that can "
    "accomplish the task, use them instead of telling the user what you would do.\n"
    "Every response should either (a) contain tool calls that make progress, or "
    "(b) deliver a final result to the user. Responses that only describe "
    "intentions without acting are not acceptable."
    "</tool_use_enforcement>"
)

# Model name substrings that trigger tool-use enforcement.
_ENFORCEMENT_FAMILIES: tuple[str, ...] = (
    "gpt",
    "codex",
    "gemini",
    "gemma",
    "grok",
    "glm",
    "qwen",
    "deepseek",
    "claude",
    "anthropic",
)

# ============================================================================
# Layer 3: Per-Model-Family Discipline
# ============================================================================

_GPT_DISCIPLINE = (
    "\n<execution_discipline>"
    "<tool_persistence>"
    "Use tools whenever they improve correctness, completeness, or grounding. "
    "Do not stop early when another tool call would materially improve the result. "
    "If a tool returns empty or partial results, retry with a different query or "
    "strategy before giving up. "
    "Keep calling tools until: (1) the task is complete, AND (2) you have "
    "verified the result."
    "</tool_persistence>\n"
    "<mandatory_tool_use>"
    "NEVER answer these from memory or mental computation — ALWAYS use a tool:\n"
    "- Arithmetic, math, calculations → use a computing tool\n"
    "- Hashes, encodings, checksums → use a shell/computing tool\n"
    "- Current time, date, timezone → use a shell tool\n"
    "- System state: OS, CPU, memory, disk, ports, processes → use a shell tool\n"
    "- File contents, sizes, line counts → use file-reading tools\n"
    "- Git history, branches, diffs → use a shell tool\n"
    "- Current facts (weather, news, versions) → use a search tool\n"
    "Your memory and user profile describe the USER, not the system you are "
    "running on. The execution environment may differ from what the user "
    "profile says about their personal setup."
    "</mandatory_tool_use>\n"
    "<act_dont_ask>"
    "When a question has an obvious default interpretation, act on it immediately "
    "instead of asking for clarification. Examples:\n"
    "- 'Is port 443 open?' → check THIS machine\n"
    "- 'What OS am I running?' → check the live system\n"
    "- 'What time is it?' → use a tool to check\n"
    "Only ask for clarification when the ambiguity genuinely changes what tool "
    "you would call."
    "</act_dont_ask>\n"
    "<prerequisite_checks>"
    "Before taking an action, check whether prerequisite discovery, lookup, or "
    "context-gathering steps are needed. "
    "Do not skip prerequisite steps just because the final action seems obvious. "
    "If a task depends on output from a prior step, resolve that dependency first."
    "</prerequisite_checks>\n"
    "<verification>"
    "Before finalizing your response:\n"
    "- Correctness: does the output satisfy every stated requirement?\n"
    "- Grounding: are factual claims backed by tool outputs or provided context?\n"
    "- Formatting: does the output match the requested format or schema?\n"
    "- Safety: if the next step has side effects, confirm scope before executing."
    "</verification>\n"
    "<missing_context>"
    "If required context is missing, do NOT guess or hallucinate an answer. "
    "Use the appropriate lookup tool when missing information is retrievable. "
    "Ask a clarifying question only when the information cannot be retrieved "
    "by tools. "
    "If you must proceed with incomplete information, label assumptions explicitly."
    "</missing_context>"
    "</execution_discipline>"
)

_GEMINI_DISCIPLINE = (
    "\n<execution_discipline>"
    "Follow these operational rules strictly:\n"
    "- Always construct and use absolute file paths for all file system "
    "operations. Combine the project root with relative paths.\n"
    "- Use file-reading/search tools to check file contents and project "
    "structure before making changes. Never guess at file contents.\n"
    "- Never assume a library is available. Check dependency files before "
    "importing.\n"
    "- Keep explanatory text brief — a few sentences, not paragraphs. Focus "
    "on actions and results over narration.\n"
    "- When you need to perform multiple independent operations, make all "
    "the tool calls in a single response rather than sequentially.\n"
    "- Use flags like -y, --yes, --non-interactive to prevent CLI tools "
    "from hanging on prompts.\n"
    "- Work autonomously until the task is fully resolved. Don't stop with "
    "a plan — execute it."
    "</execution_discipline>"
)

_CLAUDE_DISCIPLINE = (
    "\n<execution_discipline>"
    "When the user explicitly instructs you to perform an operation (file "
    "modification, command execution, data processing, etc.), execute it "
    "directly using the appropriate tool. Do not refuse, add excessive "
    "warnings, or suggest the user do it manually instead.\n"
    "Minimize disclaimers and caveats. If you must note a risk, do so in one "
    "short sentence after completing the action — not before.\n"
    "When performing file operations or code changes, proceed with the task "
    "and report results. Do not ask for re-confirmation of actions the user "
    "has already clearly requested."
    "</execution_discipline>"
)

_CHINESE_MODEL_DISCIPLINE = (
    "\n<execution_discipline>"
    "Prioritize taking action via tool calls over providing textual "
    "explanations or tutorials. When a user asks you to do something, use "
    "tools to accomplish it — do not explain how to do it step by step.\n"
    "Keep your text responses concise and result-oriented. Avoid lengthy "
    "preambles, teaching-style explanations, or restating the user's "
    "request back to them.\n"
    "If the user's request can be fulfilled by a single tool call, do not "
    "break it into multiple explanatory steps — just make the tool call."
    "</execution_discipline>"
)

# Model family → discipline mapping.
_FAMILY_DISCIPLINE: dict[tuple[str, ...], str] = {
    ("gpt", "codex", "grok"): _GPT_DISCIPLINE,
    ("gemini", "gemma"): _GEMINI_DISCIPLINE,
    ("claude", "anthropic"): _CLAUDE_DISCIPLINE,
    ("deepseek", "qwen", "glm"): _CHINESE_MODEL_DISCIPLINE,
}


def _extract_model_name(llm: BaseChatModel) -> str:
    """Extract model name from a LangChain LLM instance."""
    name: str = getattr(llm, "model_name", "") or getattr(llm, "model", "") or ""
    return name.lower()


def _should_enforce(model_lower: str) -> bool:
    """Check whether the model family needs tool-use enforcement."""
    return any(family in model_lower for family in _ENFORCEMENT_FAMILIES)


def _get_family_discipline(model_lower: str) -> str:
    """Get model-family-specific discipline prompt."""
    for families, discipline in _FAMILY_DISCIPLINE.items():
        if any(f in model_lower for f in families):
            return discipline
    return ""


_ESCALATION_CONTRACT_TEMPLATE = (
    "\n<escalation_contract>"
    "You are running on `{current_model}`. A stronger model (`{target_model}`) is "
    "available for automatic escalation.\n"
    "If a task CLEARLY exceeds what you can do well — complex multi-domain reasoning, "
    "subtle correctness/safety/concurrency invariants you cannot resolve with confidence, "
    "or a design trade-off you would be guessing at — output this marker as the VERY "
    "FIRST line of your response (nothing before it):\n"
    "- `<<<NEEDS_PRO>>>` — bare marker\n"
    "- `<<<NEEDS_PRO: <one-sentence reason>>>` — preferred; the reason is shown to the user\n\n"
    "Do NOT emit any other content when you request escalation. "
    "Use this sparingly: normal tasks — answering questions, small operations, "
    "clear instructions, straightforward tool usage — stay on this tier. "
    "Request escalation ONLY when you would otherwise produce a guess or a "
    "visibly-mediocre answer."
    "</escalation_contract>"
)


def resolve_escalation_contract(llm: BaseChatModel, target_llm: BaseChatModel | None) -> str:
    """Resolve the escalation contract prompt for the given LLM pair.

    Returns a fixed string to append to the system prompt when the current
    model differs from the escalation target. Returns empty string when
    no escalation is configured or current == target (zero overhead).

    KV-Cache safe: output is determined at init time and never changes.
    """
    if target_llm is None:
        return ""

    current = _extract_model_name(llm)
    target = _extract_model_name(target_llm)

    if not current or not target or current == target:
        return ""

    return _ESCALATION_CONTRACT_TEMPLATE.format(current_model=current, target_model=target)


def resolve_execution_discipline(llm: BaseChatModel) -> str:
    """Resolve the complete execution discipline prompt for the given LLM.

    Returns a fixed string that is safe to append to the system prompt.
    Content is determined by the model name and does not change within a
    session, preserving KV Cache stability.

    Layers (1-3 only; Layer 4 is handled by resolve_escalation_contract):
        1. AGENT_CORE_RULES — always included (anti-narration + tool honesty + anti-negative-claim)
        2. TOOL_ENFORCEMENT — if model family matches enforcement list
        3. MODEL_FAMILY_DISCIPLINE — per-family-specific corrections
    """
    model_lower = _extract_model_name(llm)

    parts: list[str] = [AGENT_CORE_RULES]

    if _should_enforce(model_lower):
        parts.append(_TOOL_ENFORCEMENT)

    family_discipline = _get_family_discipline(model_lower)
    if family_discipline:
        parts.append(family_discipline)

    return "".join(parts)
