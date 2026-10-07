"""Subagent context firewall and model downgrade governor.

Isolates high-noise exploratory and diagnostic tasks (log analysis, broad searches)
to ephemeral subagents running on lightweight models, preventing thousands of
intermediate lines from polluting the primary agent's context.

[INPUT]
- runtime.context.quiet_command_spill_types::SubagentFirewallConfig, SubagentFirewallResult (POS: Quiet
  command rewriter, output spill, and Subagent context firewall types.)

[OUTPUT]
- SubagentContextFirewall: Firewall isolating noisy background tasks and enforcing model downgrades.

[POS]
Subagent context firewall and model downgrade governor.
"""

from __future__ import annotations

import math

from .quiet_command_spill_types import SubagentFirewallConfig, SubagentFirewallResult


class SubagentContextFirewall:
    """Firewall isolating noisy background tasks and enforcing model downgrades."""

    def __init__(
        self,
        config: SubagentFirewallConfig | None = None,
        chars_per_token_ratio: float = 3.8,
    ) -> None:
        self._config = config or SubagentFirewallConfig()
        self._chars_per_token_ratio = chars_per_token_ratio

    def estimate_tokens(self, text: str) -> int:
        """Estimates token count deterministically."""
        if not text.strip():
            return 0
        return max(1, math.ceil(len(text) / self._chars_per_token_ratio))

    def should_isolate(self, task_name: str, estimated_output_chars: int = 0) -> bool:
        """Determines whether a task should be isolated behind the context firewall."""
        if not self._config.enable_firewall:
            return False

        task_lower = task_name.strip().lower()
        # Check against indicators or size threshold (>10k chars)
        is_noisy = any(ind in task_lower for ind in self._config.noisy_task_indicators)
        return is_noisy or estimated_output_chars >= 10000

    def select_model_tier(self, task_name: str, main_model: str) -> str:
        """Assigns downgraded model for the isolated subagent task."""
        if not self._config.enable_firewall:
            return main_model

        if self.should_isolate(task_name):
            return self._config.default_isolated_model
        return main_model

    def filter_and_deliver(
        self,
        task_name: str,
        intermediate_output: str,
        summary_conclusion: str,
        assigned_model: str | None = None,
    ) -> SubagentFirewallResult:
        """Blocks raw intermediate output and delivers concise conclusion to main session."""
        assigned = assigned_model or self._config.default_isolated_model

        raw_chars = len(intermediate_output)
        capped_summary = summary_conclusion[: self._config.max_delivered_summary_chars].strip()
        delivered_chars = len(capped_summary)

        raw_tokens = self.estimate_tokens(intermediate_output)
        summary_tokens = self.estimate_tokens(capped_summary)
        net_saved = max(0, raw_tokens - summary_tokens)

        return SubagentFirewallResult(
            task_name=task_name,
            assigned_model=assigned,
            raw_intermediate_chars=raw_chars,
            delivered_summary_chars=delivered_chars,
            blocked_intermediate_tokens=raw_tokens,
            delivered_summary_tokens=summary_tokens,
            net_saved_main_session_tokens=net_saved,
            summary_text=capped_summary,
        )
