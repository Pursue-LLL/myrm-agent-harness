"""Deterministic pattern matcher for Tier-0 local voice commands.

[INPUT]
Raw voice transcription utterance, VoiceBypassConfig.

[OUTPUT]
VoiceCommandMatcher returning VoiceCommandMatchResult for zero-token bypass.

[POS]
Matcher engine in context_management/voice_bypass/voice_command_matcher.py.
"""

from __future__ import annotations

import re
import time

from .voice_bypass_types import (
    VoiceActionCategory,
    VoiceBypassAction,
    VoiceBypassConfig,
    VoiceCommandMatchResult,
    VoiceIntentTier,
)


class VoiceCommandMatcher:
    """High-performance deterministic regex matcher for voice command local bypass."""

    def __init__(self, config: VoiceBypassConfig | None = None) -> None:
        self._config = config or VoiceBypassConfig()
        self._patterns: list[tuple[re.Pattern[str], VoiceBypassAction]] = self._compile_default_patterns()

    def _compile_default_patterns(self) -> list[tuple[re.Pattern[str], VoiceBypassAction]]:
        """Compile deterministic match patterns across control, navigation, and view actions."""
        raw_defs: list[tuple[str, VoiceActionCategory, str, dict[str, str]]] = [
            # Execution controls
            (r"^(停止|取消|别动|暂停运行|stop|cancel|halt)$", VoiceActionCategory.EXECUTION_CONTROL, "stop_execution", {}),
            (r"^(暂停|稍等|pause|hold on)$", VoiceActionCategory.EXECUTION_CONTROL, "pause_execution", {}),
            (r"^(重试|重新生成|再试一次|retry|regenerate)$", VoiceActionCategory.EXECUTION_CONTROL, "retry_turn", {}),
            (r"^(继续|继续执行|恢复运行|继续运行|resume|continue)$", VoiceActionCategory.EXECUTION_CONTROL, "resume_execution", {}),
            # Session navigations
            (r"^(新建会话|新对话|新建聊天|开启新会话|new chat|new session)$", VoiceActionCategory.SESSION_NAVIGATE, "new_session", {}),
            (r"^(清空会话|清空历史|清除上下文|clear chat|clear history)$", VoiceActionCategory.SESSION_NAVIGATE, "clear_session", {}),
            (r"^(打开任务板|查看任务|显示任务看板|open taskboard|show tasks)$", VoiceActionCategory.SESSION_NAVIGATE, "open_taskboard", {}),
            # Agent switcher
            (r"^(切换智能体|换个智能体|选择智能体|switch agent)$", VoiceActionCategory.AGENT_SWITCH, "switch_agent", {}),
            # System export
            (r"^(导出对话|导出记录|导出会话|export session|export chat)$", VoiceActionCategory.SYSTEM_EXPORT, "export_session", {}),
            # View scrolls
            (r"^(滚动到底部|回到最新|查看最新消息|scroll to bottom)$", VoiceActionCategory.VIEW_SCROLL, "scroll_bottom", {}),
            (r"^(查看工件|打开工件|滚动到工件|view artifact|open artifact)$", VoiceActionCategory.VIEW_SCROLL, "view_artifact", {}),
        ]

        compiled: list[tuple[re.Pattern[str], VoiceBypassAction]] = []
        for pat_str, cat, act_id, params in raw_defs:
            regex = re.compile(pat_str, re.IGNORECASE)
            action = VoiceBypassAction(action_id=act_id, category=cat, target_payload="", parameters=params)
            compiled.append((regex, action))
        return compiled

    def normalize_utterance(self, raw_text: str) -> str:
        """Strip filler words, terminal punctuation, and excess spaces."""
        text = raw_text.strip().lower()
        # Remove terminal punctuation first
        text = re.sub(r"[。？！，、,.?!~]+$", "", text).strip()
        # Repeatedly strip common speech filler prefixes
        filler_pattern = re.compile(r"^(请帮我|麻烦帮我|请你|麻烦你|请|帮我|麻烦|please|hey\s+myrm|hey)\s*", re.IGNORECASE)
        while True:
            new_text = filler_pattern.sub("", text).strip()
            if new_text == text:
                break
            text = new_text
        return text

    def match(self, raw_utterance: str) -> VoiceCommandMatchResult:
        """Evaluate raw utterance against deterministic Tier-0 bypass rules."""
        start_time = time.perf_counter()
        if not self._config.enabled or not raw_utterance or not raw_utterance.strip():
            return VoiceCommandMatchResult(
                tier=VoiceIntentTier.TIER1_AGENT_LLM,
                raw_utterance=raw_utterance,
                normalized_command="",
                is_bypass=False,
                reason="Bypass disabled or empty utterance",
            )

        normalized = self.normalize_utterance(raw_utterance)

        # If too long or contains complex intent markers, pass directly to LLM
        if len(normalized) > 30 or any(token in normalized for token in ["为什么", "怎么", "如何", "explain", "because"]):
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return VoiceCommandMatchResult(
                tier=VoiceIntentTier.TIER1_AGENT_LLM,
                raw_utterance=raw_utterance,
                normalized_command=normalized,
                is_bypass=False,
                estimated_latency_ms=elapsed_ms,
                reason="Utterance contains task reasoning semantics",
            )

        for regex, action in self._patterns:
            if regex.match(normalized):
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return VoiceCommandMatchResult(
                    tier=VoiceIntentTier.TIER0_LOCAL_BYPASS,
                    raw_utterance=raw_utterance,
                    normalized_command=normalized,
                    is_bypass=True,
                    action=action,
                    confidence=1.0,
                    tokens_saved=self._config.default_tokens_saved_estimate,
                    estimated_latency_ms=elapsed_ms,
                    reason=f"Matched deterministic Tier-0 pattern: {action.action_id}",
                )

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        return VoiceCommandMatchResult(
            tier=VoiceIntentTier.TIER1_AGENT_LLM,
            raw_utterance=raw_utterance,
            normalized_command=normalized,
            is_bypass=False,
            estimated_latency_ms=elapsed_ms,
            reason="No deterministic Tier-0 pattern matched, routed to Tier-1 Agent LLM",
        )
