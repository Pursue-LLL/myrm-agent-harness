"""One-click context compaction and fidelity-preserving purifier engine.

[INPUT]
- copy::deepcopy (POS: 消息深拷贝保障不可变性)
- langchain_core.messages::BaseMessage, HumanMessage, ToolMessage, AIMessage
- tracking.tokenomics_savings_tracker::get_global_tokenomics_tracker
- compactor.one_click_compaction_types::OneClickCompactionConfig, OneClickCompactionResult

[OUTPUT]
- OneClickContextCompactor: 一键会话上下文智能瘦身与 Token 经济学保鲜中枢
"""

from __future__ import annotations

import copy

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.tracking import (
    get_global_tokenomics_tracker,
)

from .one_click_compaction_types import (
    OneClickCompactionConfig,
    OneClickCompactionResult,
)


class OneClickContextCompactor:
    """Fidelity-preserving one-click context compactor for long multi-turn sessions."""

    @staticmethod
    def _extract_tool_summary(content: str, max_chars: int = 150) -> str:
        """Extract a single concise summary line from verbose tool output."""
        lines = [line.strip() for line in content.strip().splitlines() if line.strip()]
        if not lines:
            return "empty output"
        first_line = lines[0]
        if len(lines) == 1:
            return first_line[:max_chars]
        return f"{first_line[:80]} ... [total {len(lines)} lines]"

    @classmethod
    def compact_session_history(
        cls,
        messages: list[BaseMessage],
        session_id: str = "default_session",
        config: OneClickCompactionConfig | None = None,
    ) -> tuple[list[BaseMessage], OneClickCompactionResult]:
        """Execute one-click compaction on conversation messages preserving key decisions."""
        cfg = config or OneClickCompactionConfig()
        if not messages:
            empty_result = OneClickCompactionResult(
                session_id=session_id,
                original_messages_count=0,
                compacted_messages_count=0,
                raw_tokens=0,
                compacted_tokens=0,
                released_tokens=0,
                compression_ratio=0.0,
                estimated_cost_saved_usd=0.0,
                feedback_badge="⚡ 当前会话无消息，无需瘦身",
                purified_tool_count=0,
            )
            return [], empty_result

        # 1. Identify cutoff boundary: keep recent N human turns intact
        human_indices = [idx for idx, m in enumerate(messages) if isinstance(m, HumanMessage)]
        cutoff_index = (
            human_indices[-cfg.keep_recent_rounds]
            if len(human_indices) >= cfg.keep_recent_rounds
            else 0
        )

        compacted_messages: list[BaseMessage] = []
        purified_tools = 0
        raw_char_count = 0
        compacted_char_count = 0

        for idx, original_msg in enumerate(messages):
            orig_text = str(original_msg.content or "")
            raw_char_count += len(orig_text)

            # Keep protected recent window intact
            if idx >= cutoff_index:
                compacted_messages.append(copy.deepcopy(original_msg))
                compacted_char_count += len(orig_text)
                continue

            # In historical window: purify verbose ToolMessages
            if isinstance(original_msg, ToolMessage) and len(orig_text) >= cfg.min_content_length_to_purify:
                summary = cls._extract_tool_summary(orig_text)
                tool_name = getattr(original_msg, "name", None) or "tool"
                call_id = getattr(original_msg, "tool_call_id", "")
                purified_content = (
                    f"[COMPACTED_TOOL_RESULT: tool={tool_name}, "
                    f"id={call_id}, original_length={len(orig_text)} chars, summary='{summary}']"
                )
                new_msg = copy.deepcopy(original_msg)
                new_msg.content = purified_content
                compacted_messages.append(new_msg)
                compacted_char_count += len(purified_content)
                purified_tools += 1
            else:
                compacted_messages.append(copy.deepcopy(original_msg))
                compacted_char_count += len(orig_text)

        # 2. Token & Economy calculations
        ratio = cfg.estimate_char_to_token_ratio
        raw_tokens = max(1, int(raw_char_count / ratio))
        compacted_tokens = max(1, int(compacted_char_count / ratio))
        released_tokens = max(0, raw_tokens - compacted_tokens)
        comp_ratio = round((released_tokens / raw_tokens) if raw_tokens > 0 else 0.0, 4)

        # 3. Record in Tokenomics Tracker
        tracker = get_global_tokenomics_tracker()
        savings_event = tracker.record_compaction(
            operator_name="one_click_compact",
            raw_tokens=raw_tokens,
            compacted_tokens=compacted_tokens,
            model_name=cfg.model_name,
            details={"purified_tools": purified_tools, "session_id": session_id},
        )

        cost_saved = savings_event.estimated_cost_saved_usd

        # 4. Formulate intuitive feedback badge for WebUI & Desktop
        if released_tokens > 0:
            badge = (
                f"✨ 已成功为您瘦身 {comp_ratio * 100:.1f}% 上下文，"
                f"释放 {released_tokens:,} Tokens · 约节省 ${cost_saved:.4f}"
            )
        else:
            badge = "⚡ 会话上下文结构紧凑，已达最优保鲜状态"

        result = OneClickCompactionResult(
            session_id=session_id,
            original_messages_count=len(messages),
            compacted_messages_count=len(compacted_messages),
            raw_tokens=raw_tokens,
            compacted_tokens=compacted_tokens,
            released_tokens=released_tokens,
            compression_ratio=comp_ratio,
            estimated_cost_saved_usd=cost_saved,
            feedback_badge=badge,
            purified_tool_count=purified_tools,
            details={"cutoff_index": cutoff_index},
        )

        return compacted_messages, result
