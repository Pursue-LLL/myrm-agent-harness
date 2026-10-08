"""Tail-positioned status tag serializer and cache-friendly prompt injector for runtime state ledgers.

[INPUT]
- RuntimeStateSnapshot: Deterministically compiled status snapshot.
- RuntimeLedgerConfig: Settings governing tag name, token budget, and update policy.

[OUTPUT]
- TailLedgerInjector: Serializer and context tail injector ensuring 100% prefix cache preservation.

[POS]
Formatting and cache-friendly tail injection layer in runtime state ledger suite.
"""

from __future__ import annotations

import re
from typing import Sequence

from .runtime_ledger_types import (
    LedgerInjectionResult,
    LedgerUpdatePolicy,
    QuotaConstraint,
    RuntimeLedgerConfig,
    RuntimeStateSnapshot,
    TodoProgress,
)


class TailLedgerInjector:
    """Renders structured <agent_status> tags and mounts them strictly at the prompt tail."""

    def __init__(self, config: RuntimeLedgerConfig | None = None) -> None:
        self._config = config or RuntimeLedgerConfig()
        tag = re.escape(self._config.status_tag_name)
        self._tag_pattern = re.compile(rf"<{tag}>[\s\S]*?</{tag}>", re.IGNORECASE)

    def render_status_tag(self, snapshot: RuntimeStateSnapshot) -> str:
        """Renders structured, model-readable status tag respecting token budgets and priority tiers."""
        tag_name = self._config.status_tag_name
        lines: list[str] = [f"<{tag_name}>"]

        header_items = [f"Turn: {snapshot.turn_index}"]
        if self._config.enable_timestamp and snapshot.current_timestamp_iso:
            header_items.append(f"Time: {snapshot.current_timestamp_iso}")
        lines.append(f"[{' | '.join(header_items)}]")

        # 1. Tier 1: Constraints (Highest Priority)
        if snapshot.constraints:
            lines.append("Constraints:")
            for c in snapshot.constraints:
                status_mark = "EXHAUSTED ❌" if c.is_exhausted else f"{c.remaining} remaining"
                lines.append(f"- {c.name}: used {c.used_count}/{c.max_limit} {c.unit} ({status_mark})")

        # 2. Tier 2: TODO Progress
        if snapshot.todos:
            lines.append("TODO Progress:")
            for t in snapshot.todos:
                box = "[✓]" if t.is_completed else "[ ]"
                lines.append(f"- {box} {t.title}")

        # 3. Tier 3: Recent Milestones
        if snapshot.recent_milestones:
            lines.append("Recent Milestones:")
            for m in snapshot.recent_milestones[:5]:
                lines.append(f"- {m}")

        # 4. Tier 4: Tool Invocations
        if snapshot.tool_call_counts:
            counts_str = ", ".join(f"{k}: {v}" for k, v in sorted(snapshot.tool_call_counts.items()))
            lines.append(f"Tool Invocations: {counts_str}")

        lines.append(f"</{tag_name}>")
        raw_text = "\n".join(lines)

        # Budget cap enforcement
        token_cap = self._config.max_ledger_tokens
        char_cap = token_cap * 4
        if len(raw_text) > char_cap:
            raw_text = self._condense_to_budget(snapshot, char_cap)

        return raw_text

    def inject_into_text(
        self,
        base_text: str,
        snapshot: RuntimeStateSnapshot,
    ) -> tuple[str, LedgerInjectionResult]:
        """Injects rendered status tag into text tail, adhering to REPLACE or APPEND policy."""
        rendered = self.render_status_tag(snapshot)
        token_est = max(1, (len(rendered) + 3) // 4)
        policy = self._config.update_policy

        if policy == LedgerUpdatePolicy.REPLACE:
            # Strip existing status tag if present, then append to tail
            stripped_base = self._tag_pattern.sub("", base_text).rstrip()
            expanded_text = f"{stripped_base}\n\n{rendered}" if stripped_base else rendered
        else:
            # Append policy: monotonically append to tail
            trimmed_base = base_text.rstrip()
            expanded_text = f"{trimmed_base}\n\n{rendered}" if trimmed_base else rendered

        result = LedgerInjectionResult(
            rendered_tag=rendered,
            token_estimate=token_est,
            policy_used=policy,
            injected_into_tail=True,
        )
        return expanded_text, result

    def _condense_to_budget(self, snapshot: RuntimeStateSnapshot, char_cap: int) -> str:
        """Priority condensation shedding lower-priority fields to fit budget."""
        tag_name = self._config.status_tag_name
        lines: list[str] = [
            f"<{tag_name}>",
            f"[Turn: {snapshot.turn_index}]",
        ]
        if snapshot.constraints:
            lines.append("Constraints:")
            for c in snapshot.constraints:
                status_mark = "EXHAUSTED" if c.is_exhausted else f"{c.remaining} left"
                lines.append(f"- {c.name}: {c.used_count}/{c.max_limit} ({status_mark})")

        if snapshot.todos:
            lines.append("TODO:")
            for t in snapshot.todos:
                box = "[✓]" if t.is_completed else "[ ]"
                lines.append(f"- {box} {t.title}")

        lines.append(f"</{tag_name}>")
        condensed = "\n".join(lines)
        return condensed[:char_cap]
