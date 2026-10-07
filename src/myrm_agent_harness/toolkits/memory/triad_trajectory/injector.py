"""Anti-Loop Pre-Prompt Snapshot Injector for long-horizon task execution.

[INPUT]
- Internal: ledger.py (TriadStateLedger), types.py (AntiLoopPromptSnapshot)
- External: math

[OUTPUT]
- AntiLoopPromptInjector: Synthesizes high-density, low-token snapshots preventing loop traps and steering loss.

[POS]
Harness framework layer executing atomic context injection before every LLM invocation.
"""

from .ledger import TriadStateLedger
from .types import AntiLoopPromptSnapshot


class AntiLoopPromptInjector:
    """Synthesizes high-density pre-prompt snapshots strictly bounded by token budgets."""

    DEFAULT_MAX_TOKENS = 150

    @classmethod
    def build_snapshot(
        cls,
        ledger: TriadStateLedger,
        step_hint: str = "",
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> AntiLoopPromptSnapshot:
        """Construct an atomic snapshot containing prioritized dead-end rules and active steerings."""
        failed_attempts = ledger.failed_attempts
        active_steerings = ledger.active_steerings
        milestones = ledger.milestones

        latest_milestone = milestones[-1] if milestones else None
        latest_milestone_title = latest_milestone.title if latest_milestone else None

        # Prioritize relevant failed attempts if step hint is given, else latest attempts
        prioritized_attempts = cls._prioritize_attempts(failed_attempts, step_hint)

        dead_end_rules: list[str] = []
        for attempt in prioritized_attempts:
            rule_str = f"禁试: {attempt.prohibited_rule or attempt.dead_end_pattern} (根因: {attempt.error_summary})"
            dead_end_rules.append(rule_str)

        steering_rules: list[str] = [
            f"约束: {steering.distilled_constraint}" for steering in active_steerings
        ]

        # Construct XML block and dynamically trim to budget
        xml_block, token_count = cls._format_and_budget(
            task_id=ledger.task_id,
            dead_ends=dead_end_rules,
            steerings=steering_rules,
            milestone_title=latest_milestone_title,
            max_tokens=max_tokens,
        )

        return AntiLoopPromptSnapshot(
            task_id=ledger.task_id,
            snapshot_token_estimate=token_count,
            dead_end_rules_injected=dead_end_rules,
            active_user_steerings_injected=steering_rules,
            latest_milestone_title=latest_milestone_title,
            formatted_prompt_block=xml_block,
        )

    @classmethod
    def _prioritize_attempts(
        cls,
        attempts: list,
        step_hint: str,
    ) -> list:
        if not step_hint:
            # Reverse order (latest first), top 4
            return list(reversed(attempts))[:4]

        hint_lower = step_hint.lower()
        matched = []
        unmatched = []

        for att in reversed(attempts):
            if att.dead_end_pattern.lower() in hint_lower or att.action_attempted.lower() in hint_lower:
                matched.append(att)
            else:
                unmatched.append(att)

        return (matched + unmatched)[:4]

    @classmethod
    def _format_and_budget(
        cls,
        task_id: str,
        dead_ends: list[str],
        steerings: list[str],
        milestone_title: str | None,
        max_tokens: int,
    ) -> tuple[str, int]:
        """Format the triad block and prune items if token estimate exceeds budget."""
        lines = [f'<task_triad_blackbox task_id="{task_id}">']

        if steerings:
            lines.append("【最新在途用户约束 / In-Flight Constraints】:")
            for s in steerings:
                lines.append(f"  - {s}")

        if dead_ends:
            lines.append("【已试死胡同禁令 / Prohibited Dead Ends】:")
            for d in dead_ends:
                lines.append(f"  - {d}")

        if milestone_title:
            lines.append("【已验证里程碑 / Verified Milestone】:")
            lines.append(f"  - 已完成: {milestone_title}")

        lines.append("</task_triad_blackbox>")

        formatted = "\n".join(lines)
        token_estimate = max(1, len(formatted) // 4)

        # Truncate oldest dead-ends if budget exceeded
        while token_estimate > max_tokens and len(dead_ends) > 1:
            dead_ends.pop()
            return cls._format_and_budget(task_id, dead_ends, steerings, milestone_title, max_tokens)

        return formatted, token_estimate
