"""ReAct trap remediation engine for production LLM Agent contexts.

Resolves the four canonical ReAct context degradation traps:
1. Observation Expansion (Post-consumption tool result folding)
2. Rule Drift (Recency-effect dynamic rule re-anchoring)
3. Error Contamination (Failed retry trajectory pruning)
4. Thought Accumulation (Older thought chain decay)

[INPUT]
- runtime.context.context_engineering_types::ContextRemediationConfig, RemediationResult, TrapType (POS:
  Context engineering types and data protocols for ReAct trap remediation and ACI design.)

[OUTPUT]
- ReActTrapRemediator: Deterministic processor addressing the 4 ReAct context traps.

[POS]
ReAct trap remediation engine for production LLM Agent contexts.
"""

from __future__ import annotations

import re

from myrm_agent_harness.runtime.context.context_engineering_types import (
    ContextRemediationConfig,
    RemediationResult,
    TrapType,
)


class ReActTrapRemediator:
    """Deterministic processor addressing the 4 ReAct context traps."""

    def __init__(self, config: ContextRemediationConfig | None = None) -> None:
        self.config = config or ContextRemediationConfig()

    def remediate(
        self,
        messages: list[dict[str, str]],
        core_rules: list[str] | None = None,
    ) -> RemediationResult:
        """Execute full remediation pipeline over message history."""
        curr = [dict(m) for m in messages]
        initial_chars = sum(len(m.get("content", "")) for m in curr)

        folded_count = 0
        pruned_errors = 0
        decayed_thoughts = 0
        reanchored = False

        if TrapType.OBSERVATION_EXPANSION in self.config.enabled_traps:
            curr, folded_count = self.fold_consumed_tool_outputs(curr)

        if TrapType.ERROR_CONTAMINATION in self.config.enabled_traps:
            curr, pruned_errors = self.prune_failed_trajectories(curr)

        if TrapType.THOUGHT_ACCUMULATION in self.config.enabled_traps:
            curr, decayed_thoughts = self.decay_thoughts(curr)

        if TrapType.RULE_DRIFT in self.config.enabled_traps and core_rules:
            curr, reanchored = self.reanchor_rules(curr, core_rules)

        final_chars = sum(len(m.get("content", "")) for m in curr)
        saved_chars = max(0, initial_chars - final_chars)

        return RemediationResult(
            processed_messages=curr,
            folded_tool_count=folded_count,
            pruned_failed_trajectories=pruned_errors,
            reanchored=reanchored,
            decayed_thoughts_count=decayed_thoughts,
            saved_chars_estimate=saved_chars,
        )

    def fold_consumed_tool_outputs(
        self, messages: list[dict[str, str]]
    ) -> tuple[list[dict[str, str]], int]:
        """Fold bulky tool observations in historic turns that have been consumed."""
        out: list[dict[str, str]] = []
        folded = 0
        threshold = self.config.fold_tool_length_threshold
        keep_recent = self.config.keep_recent_raw_tool_turns

        # Identify tool messages
        tool_indices: list[int] = [
            i
            for i, m in enumerate(messages)
            if m.get("role") in ("tool", "function")
            or "tool_call_id" in m
            or m.get("name") is not None
        ]

        if not tool_indices:
            return messages, 0

        # Protect the most recent keep_recent tool turns from folding
        protected_indices = set(tool_indices[-keep_recent:]) if keep_recent > 0 else set()

        for idx, msg in enumerate(messages):
            new_msg = dict(msg)
            is_tool = idx in tool_indices
            content = new_msg.get("content", "")

            if is_tool and idx not in protected_indices and len(content) > threshold:
                preview = content[:80].replace("\n", " ").strip()
                folded_content = (
                    f"[Tool Result: Consumed by agent, folded payload | "
                    f"original_length={len(content)} chars | preview: {preview}...]"
                )
                new_msg["content"] = folded_content
                folded += 1

            out.append(new_msg)

        return out, folded

    def prune_failed_trajectories(
        self, messages: list[dict[str, str]]
    ) -> tuple[list[dict[str, str]], int]:
        """Prune redundant failure stack traces when a tool subsequently succeeded."""
        out: list[dict[str, str]] = []
        pruned_count = 0
        error_keywords = ("error:", "exception:", "traceback", "failed:", "errno")

        # First scan for failed tool messages followed by success
        tool_status: list[dict[str, str]] = []
        for m in messages:
            tool_status.append(dict(m))

        # Identify tool messages with error followed by subsequent successful tool
        n = len(tool_status)
        for i in range(n):
            msg = tool_status[i]
            role = msg.get("role", "")
            content = msg.get("content", "")
            is_tool = role in ("tool", "function") or "tool_call_id" in msg

            if not is_tool:
                out.append(msg)
                continue

            content_lower = content.lower()
            is_error = any(kw in content_lower for kw in error_keywords)

            # Check if there is a later successful tool execution
            subsequent_success = False
            if is_error:
                for j in range(i + 1, n):
                    next_m = tool_status[j]
                    next_role = next_m.get("role", "")
                    next_is_tool = next_role in ("tool", "function") or "tool_call_id" in next_m
                    if next_is_tool:
                        next_cnt = next_m.get("content", "").lower()
                        if not any(kw in next_cnt for kw in error_keywords):
                            subsequent_success = True
                            break

            if is_error and subsequent_success and len(content) > 120:
                # Extract concise error message line, skipping generic traceback headers
                lines = [ln.strip() for ln in content.strip().split("\n") if ln.strip()]
                error_summary = ""
                for ln in reversed(lines):
                    if any(kw in ln.lower() for kw in ("error", "exception", "failed", "errno")):
                        error_summary = ln[:100]
                        break
                if not error_summary and lines:
                    error_summary = lines[-1][:100]

                sanitized = (
                    f"[Tool Recovery: Prior error pruned after subsequent success | "
                    f"summary: {error_summary}]"
                )
                msg["content"] = sanitized
                pruned_count += 1

            out.append(msg)

        return out, pruned_count

    def decay_thoughts(
        self, messages: list[dict[str, str]]
    ) -> tuple[list[dict[str, str]], int]:
        """Decay older internal reasoning chains while preserving recent thoughts."""
        out: list[dict[str, str]] = []
        decayed = 0
        thought_regex = re.compile(r"<thought>([\s\S]*?)</thought>", re.IGNORECASE)

        # Locate assistant messages containing thoughts
        assistant_indices = [
            i
            for i, m in enumerate(messages)
            if m.get("role") == "assistant" and "<thought>" in m.get("content", "")
        ]

        keep_turns = self.config.max_active_thoughts_turns
        protected_indices = (
            set(assistant_indices[-keep_turns:]) if keep_turns > 0 else set()
        )

        for idx, msg in enumerate(messages):
            new_msg = dict(msg)
            content = new_msg.get("content", "")

            if idx in assistant_indices and idx not in protected_indices:

                def _replace_thought(match: re.Match[str]) -> str:
                    nonlocal decayed
                    decayed += 1
                    return '<thought status="decayed">[Reasoning completed and offloaded]</thought>'

                new_msg["content"] = thought_regex.sub(_replace_thought, content)

            out.append(new_msg)

        return out, decayed

    def reanchor_rules(
        self, messages: list[dict[str, str]], core_rules: list[str]
    ) -> tuple[list[dict[str, str]], bool]:
        """Re-anchor core behavioral rules near the end of context to combat recency drift."""
        if not messages or not core_rules:
            return messages, False

        turn_count = len(messages)
        if turn_count < self.config.reanchor_turn_interval:
            return messages, False

        # Format re-anchoring block
        rules_str = "\n".join(f"- {r}" for r in core_rules)
        reanchor_block = (
            f"\n\n<anchored_system_rules>\n"
            f"[CRITICAL REMINDER: Recency Anchor for Active Constraints]\n"
            f"{rules_str}\n"
            f"</anchored_system_rules>"
        )

        out = [dict(m) for m in messages]
        # Attach to the last user message or last message
        target_idx = -1
        for i in range(len(out) - 1, -1, -1):
            if out[i].get("role") == "user":
                target_idx = i
                break

        if target_idx == -1:
            target_idx = len(out) - 1

        curr_content = out[target_idx].get("content", "")
        if "<anchored_system_rules>" not in curr_content:
            out[target_idx]["content"] = curr_content + reanchor_block
            return out, True

        return out, False
