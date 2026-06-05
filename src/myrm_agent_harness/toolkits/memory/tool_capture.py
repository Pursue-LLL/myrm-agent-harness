"""Tool-scoped memory capture hook.

Captures tool-level behavioral rules from two zero-LLM-cost paths:

1. **Edict detection**: Regex-based detection of user prohibitions and
   preferences (Chinese + English) that reference specific tools.
   Matched edicts are stored as CRITICAL-priority ProceduralMemory
   rules scoped to the relevant tool.

2. **Repeated failure recording**: When a tool fails twice or more within
   the same session, a NORMAL-priority rule is recorded to guide future
   tool selection.

Both paths piggyback on the existing HookEvent system and store results
via the standard ProceduralMemory pipeline (inheriting security scanning,
scope isolation, and prompt injection).

[INPUT]
- agent.hooks.types::HookResult, PostToolUsePayload, PostToolUseFailurePayload
- toolkits.memory.types::ProceduralMemory, ToolRulePriority, RuleSource

[OUTPUT]
- ToolMemoryCaptureHook: Async hook for POST_TOOL_USE_FAILURE
- extract_tool_edicts: Standalone edict extraction (testable without hook)
- associate_tool: Keyword-based tool name association for edicts

[POS]
Tool-scoped memory capture via regex edicts + failure counting.
Zero LLM cost. Integrates with HookRegistry via CallableHookDefinition.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from myrm_agent_harness.core.hooks.types import HookResult
from myrm_agent_harness.toolkits.memory.types import (
    ProceduralMemory,
    RuleSource,
    ToolRulePriority,
)

logger = logging.getLogger(__name__)

# ── Edict patterns (EN + ZH) ────────────────────────────────────────

_EN_EDICT_PATTERNS: list[tuple[re.Pattern[str], Literal["en", "zh"]]] = [
    (
        re.compile(
            r"\b(?:never|don'?t|do not|stop|forbid|prohibit|avoid)\b\s+(?:use|using|run|running|execute|executing)\s+(.+?)(?:[.,!?\n]|$)",
            re.IGNORECASE,
        ),
        "en",
    ),
    (
        re.compile(
            r"\b(?:never|don'?t|do not)\b\s+(.+?)(?:\s+(?:again|anymore|ever))?(?:[.,!?\n]|$)",
            re.IGNORECASE,
        ),
        "en",
    ),
    (
        re.compile(
            r"\balways\s+(?:use|prefer|choose)\s+(.+?)(?:\s+(?:instead|over|rather))?(?:[.,!?\n]|$)",
            re.IGNORECASE,
        ),
        "en",
    ),
]

_ZH_EDICT_PATTERNS: list[tuple[re.Pattern[str], Literal["en", "zh"]]] = [
    (
        re.compile(r"(?:禁止|不要|不准|别|不许|严禁)(?:再)?(?:用|使用|执行|运行)(.+?)(?:[，。！？\n]|$)"),
        "zh",
    ),
    (re.compile(r"(?:禁止|不要|不准|别|不许|严禁)(.+?)(?:[，。！？\n]|$)"), "zh"),
    (re.compile(r"(?:必须|一定要|总是|始终)(?:用|使用)(.+?)(?:[，。！？\n]|$)"), "zh"),
]

_ALL_EDICT_PATTERNS = _EN_EDICT_PATTERNS + _ZH_EDICT_PATTERNS


@dataclass(frozen=True, slots=True)
class DetectedEdict:
    """A user edict extracted from conversation text."""

    rule_text: str
    language: Literal["zh", "en"]
    original_match: str


def extract_tool_edicts(text: str) -> list[DetectedEdict]:
    """Extract user edicts (prohibitions/mandates) from text.

    Returns a deduplicated list of detected edicts. Each edict
    captures the user's explicit instruction about tool usage.
    """
    edicts: list[DetectedEdict] = []
    seen: set[str] = set()

    for pattern, lang in _ALL_EDICT_PATTERNS:
        for match in pattern.finditer(text):
            full = match.group(0).strip()
            captured = match.group(1).strip() if match.lastindex and match.lastindex >= 1 else full
            if len(captured) < 3 or len(captured) > 200:
                continue
            key = captured.lower()
            if key in seen:
                continue
            seen.add(key)
            edicts.append(DetectedEdict(rule_text=captured, language=lang, original_match=full))

    return edicts


# ── Tool name association ────────────────────────────────────────────

_TOOL_KEYWORD_MAP: dict[str, list[str]] = {
    "bash_code_execute_tool": [
        "bash",
        "shell",
        "terminal",
        "command",
        "sudo",
        "rm",
        "命令",
        "终端",
    ],
    "web_search_tool": ["search", "google", "搜索", "检索"],
    "web_fetch_tool": ["fetch", "url", "website", "网页", "抓取", "访问"],
    "file_write_tool": ["write", "file", "create file", "写文件", "创建文件"],
    "file_edit_tool": ["edit", "modify", "编辑", "修改"],
    "file_read_tool": ["read", "cat", "读取", "查看"],
}


def associate_tool(edict_text: str, recent_tool: str | None) -> str | None:
    """Associate an edict with a tool name.

    Priority: keyword matching > most recently used tool.
    """
    text_lower = edict_text.lower()
    for tool_name, keywords in _TOOL_KEYWORD_MAP.items():
        if any(kw in text_lower for kw in keywords):
            return tool_name
    return recent_tool


# ── Failure tracker ──────────────────────────────────────────────────


@dataclass
class _FailureTracker:
    """Per-session failure counter for tools."""

    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    recorded: set[str] = field(default_factory=set)

    def record_failure(self, tool_name: str) -> int:
        self.counts[tool_name] += 1
        return self.counts[tool_name]

    def should_create_rule(self, tool_name: str, threshold: int = 2) -> bool:
        return self.counts[tool_name] >= threshold and tool_name not in self.recorded

    def mark_recorded(self, tool_name: str) -> None:
        self.recorded.add(tool_name)


# ── Hook implementation ──────────────────────────────────────────────

_FAILURE_THRESHOLD = 2


class ToolMemoryCaptureHook:
    """Captures tool-scoped rules from user edicts and repeated failures.

    Register with HookRegistry for POST_TOOL_USE_FAILURE events.

    Usage::

        hook = ToolMemoryCaptureHook()
        session = MemorySession(manager=mm, chat_id="...", tool_capture_hook=hook)
        registry.register(HookEvent.POST_TOOL_USE_FAILURE, CallableHookDefinition(fn=hook.on_post_tool_failure))
    """

    def __init__(self) -> None:
        self._failure_tracker = _FailureTracker()
        self._pending_rules: list[ProceduralMemory] = []
        self._last_tool_name: str | None = None

    @property
    def pending_rules(self) -> list[ProceduralMemory]:
        """Rules captured but not yet persisted (for batch store)."""
        return list(self._pending_rules)

    def drain_pending(self) -> list[ProceduralMemory]:
        """Return and clear all pending rules."""
        rules = self._pending_rules
        self._pending_rules = []
        return rules

    async def on_post_tool_use(self, event: str, payload: dict[str, object]) -> HookResult:
        """Handle POST_TOOL_USE: track last used tool."""
        tool_name = str(payload.get("tool_name", ""))
        if tool_name:
            self._last_tool_name = tool_name
        return HookResult(hook_type="tool_memory_capture", success=True)

    async def on_user_turn(self, event: str, payload: dict[str, object]) -> HookResult:
        """Handle USER_TURN: detect edicts in user input."""
        user_input = str(payload.get("user_input", ""))
        if not user_input:
            return HookResult(hook_type="tool_memory_capture", success=True)

        edicts = extract_tool_edicts(user_input)
        for edict in edicts:
            tool_name = associate_tool(edict.rule_text, self._last_tool_name)
            if tool_name:
                rule = ProceduralMemory(
                    content=edict.rule_text,
                    trigger=f"User edict for {tool_name}",
                    action=f"Strictly follow user edict: {edict.rule_text}",
                    tool_name=tool_name,
                    tool_rule_priority=ToolRulePriority.CRITICAL,
                    source=RuleSource.USER_EXPLICIT,
                    language=edict.language,
                    priority=100,
                )
                self._pending_rules.append(rule)
                logger.info(
                    "[ToolCapture] User edict → tool=%s edict='%s'",
                    tool_name,
                    edict.rule_text,
                )

        return HookResult(hook_type="tool_memory_capture", success=True)

    async def on_post_tool_failure(self, event: str, payload: dict[str, object]) -> HookResult:
        """Handle POST_TOOL_USE_FAILURE: track repeated failures."""
        tool_name = str(payload.get("tool_name", ""))
        error = str(payload.get("error", ""))

        if not tool_name:
            return HookResult(hook_type="tool_memory_capture", success=True)

        count = self._failure_tracker.record_failure(tool_name)

        if self._failure_tracker.should_create_rule(tool_name, _FAILURE_THRESHOLD):
            self._failure_tracker.mark_recorded(tool_name)
            rule = ProceduralMemory(
                content=f"Tool '{tool_name}' failed {count} times in this session",
                trigger=f"{tool_name} repeated failure",
                action=f"Consider alternative approach when using {tool_name}. Last error: {error[:200]}",
                tool_name=tool_name,
                tool_rule_priority=ToolRulePriority.NORMAL,
                source=RuleSource.AGENT_SELF,
                language="en",
                priority=30,
            )
            self._pending_rules.append(rule)
            logger.info(
                "[ToolCapture] Repeated failure → tool=%s count=%d",
                tool_name,
                count,
            )

        return HookResult(hook_type="tool_memory_capture", success=True, output=f"failures={count}")

    def reset_session(self) -> None:
        """Reset failure counters for a new session."""
        self._failure_tracker = _FailureTracker()
        self._pending_rules = []
        self._last_tool_name = None
