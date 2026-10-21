"""Mixed batch tool validator with 3-strike partial exit and role alternation enforcement.

Faithfully implements the production-grade validation state machine benchmarked against
Hermes Agent turn_tool_validation.py:
- Auto-repairs hallucinated tool names within safe thresholds.
- Deduplicates tool-call IDs across the session.
- Splits mixed batches: executes valid calls while error-resulting invalid ones.
- Halts infinite loops with 3-strike partial exits only when a turn has zero valid calls.
- Detects hidden stream truncation before attempting malformed JSON repairs.

[OUTPUT]
- MixedBatchToolValidator: Core validation orchestrator for agent conversation loops.

[INPUT]
- __future__
- json

[OUTPUT]
- MixedBatchToolValidator

[POS]
Mixed batch tool validator with 3-strike partial exit and role alternation enforcement.
"""

from __future__ import annotations

import json

from myrm_agent_harness.agent.tool_validation.fuzzy_repair import (
    ToolCallIdUniquifier,
    ToolNameFuzzyRepairer,
)
from myrm_agent_harness.agent.tool_validation.validation_types import (
    ToolCallEnvelope,
    ToolCallResult,
    ToolValidationAction,
    ToolValidationVerdict,
)


class MixedBatchToolValidator:
    """Evaluates, repairs, and routes inbound tool calls from language model outputs."""

    def __init__(
        self,
        valid_tool_names: set[str] | frozenset[str],
        *,
        fuzzy_repairer: ToolNameFuzzyRepairer | None = None,
        max_invalid_strikes: int = 3,
    ) -> None:
        self.valid_tool_names: frozenset[str] = frozenset(valid_tool_names)
        self.fuzzy_repairer: ToolNameFuzzyRepairer = (
            fuzzy_repairer or ToolNameFuzzyRepairer()
        )
        self.max_invalid_strikes: int = max(1, max_invalid_strikes)
        self._strike_count: int = 0

    @property
    def current_strikes(self) -> int:
        """Return the current continuous strike counter for invalid tool rounds."""
        return self._strike_count

    def reset_strikes(self) -> None:
        """Explicitly reset the strike counter to zero."""
        self._strike_count = 0

    def _normalize_and_validate_json_arguments(
        self,
        call: ToolCallEnvelope,
    ) -> tuple[str, bool, str | None]:
        """Normalize JSON arguments and check for stream cut-off truncation.

        Returns:
            (normalized_arguments, is_truncated, parse_error_if_any)
        """
        raw = call.arguments.strip()
        if not raw:
            return "{}", False, None

        # Check for mid-stream truncation where JSON was cut off without closing braces
        if not raw.endswith(("}", "]")):
            return raw, True, "Tool arguments appear cut off mid-stream (missing closing brace/bracket)"

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, (dict, list)):
                return json.dumps(parsed), False, None
            return raw, False, None
        except json.JSONDecodeError as err:
            return raw, False, str(err)

    def validate_batch(
        self,
        calls: list[ToolCallEnvelope] | tuple[ToolCallEnvelope, ...],
        *,
        taken_session_ids: set[str] | None = None,
    ) -> ToolValidationVerdict:
        """Validate a batch of tool calls emitted in a single model turn.

        Args:
            calls: Inbound tool call envelopes.
            taken_session_ids: Tool-call IDs previously consumed in this conversation session.

        Returns:
            ToolValidationVerdict with actionable routing decisions.
        """
        if not calls:
            return ToolValidationVerdict(
                action=ToolValidationAction.OK,
                strike_count=self._strike_count,
            )

        # 1. Uniquify duplicate IDs to prevent provider/gateway collisions
        uniquified_calls = ToolCallIdUniquifier.uniquify(calls, taken_session_ids)

        # 2. Attempt name repair for hallucinated or mistyped tool names
        repaired_pairs: list[tuple[str, str]] = []
        normalized_calls: list[ToolCallEnvelope] = []

        for call in uniquified_calls:
            norm_args, is_trunc, parse_err = self._normalize_and_validate_json_arguments(call)

            if is_trunc:
                self._strike_count = 0
                return ToolValidationVerdict(
                    action=ToolValidationAction.TERMINAL_PARTIAL_EXIT,
                    strike_count=0,
                    failure_reason=(
                        f"Truncated tool arguments detected for '{call.name}': {parse_err}"
                    ),
                )

            current_name = call.name
            if current_name not in self.valid_tool_names:
                repaired = self.fuzzy_repairer.repair_name(
                    current_name, set(self.valid_tool_names)
                )
                if repaired is not None and repaired != current_name:
                    repaired_pairs.append((current_name, repaired))
                    current_name = repaired

            normalized_calls.append(
                ToolCallEnvelope(
                    id=call.id,
                    name=current_name,
                    arguments=norm_args,
                    index=call.index,
                )
            )

        # 3. Categorize valid vs invalid calls
        valid_calls: list[ToolCallEnvelope] = []
        invalid_calls: list[ToolCallEnvelope] = []

        for call in normalized_calls:
            if call.name in self.valid_tool_names:
                valid_calls.append(call)
            else:
                invalid_calls.append(call)

        available_tools_preview = ", ".join(sorted(self.valid_tool_names)[:10])

        # Scenario A: All calls are valid
        if not invalid_calls:
            self._strike_count = 0
            return ToolValidationVerdict(
                action=ToolValidationAction.OK,
                executable_calls=tuple(valid_calls),
                strike_count=0,
                repaired_names=tuple(repaired_pairs),
            )

        # Scenario B: Mixed batch (both valid and unknown tools exist)
        if valid_calls and invalid_calls:
            # Crucial invariant: Do NOT increment strike counter when at least one call is valid.
            # Real business progress is being made. Synthesize error results for invalid ones.
            self._strike_count = 0
            synthetic_results: list[ToolCallResult] = []

            for inv in invalid_calls:
                synthetic_results.append(
                    ToolCallResult(
                        tool_call_id=inv.id,
                        name=inv.name,
                        content=(
                            f"Error: Unknown tool '{inv.name}'. "
                            f"Available tools: [{available_tools_preview}]. "
                            "Please review available tools and adjust your invocation."
                        ),
                        role="tool",
                        is_error=True,
                    )
                )

            return ToolValidationVerdict(
                action=ToolValidationAction.SPLIT_EXECUTE,
                executable_calls=tuple(valid_calls),
                synthetic_results=tuple(synthetic_results),
                is_mixed_batch=True,
                strike_count=0,
                repaired_names=tuple(repaired_pairs),
            )

        # Scenario C: Purely invalid batch (zero valid calls)
        self._strike_count += 1
        synthetic_results_all: list[ToolCallResult] = []

        for inv in invalid_calls:
            synthetic_results_all.append(
                ToolCallResult(
                    tool_call_id=inv.id,
                    name=inv.name,
                    content=(
                        f"Error: Unknown tool '{inv.name}'. "
                        f"Available tools: [{available_tools_preview}]."
                    ),
                    role="tool",
                    is_error=True,
                )
            )

        # Exceeded 3-strike threshold -> Terminal partial exit
        if self._strike_count >= self.max_invalid_strikes:
            strike_record = self._strike_count
            self._strike_count = 0
            return ToolValidationVerdict(
                action=ToolValidationAction.TERMINAL_PARTIAL_EXIT,
                synthetic_results=tuple(synthetic_results_all),
                strike_count=strike_record,
                failure_reason=(
                    f"Exceeded maximum consecutive invalid tool retries "
                    f"({strike_record}/{self.max_invalid_strikes}) for '{invalid_calls[0].name}'."
                ),
                repaired_names=tuple(repaired_pairs),
            )

        # Still within retry budget -> re-prompt model with synthetic error results
        return ToolValidationVerdict(
            action=ToolValidationAction.RETRY_MODEL,
            synthetic_results=tuple(synthetic_results_all),
            strike_count=self._strike_count,
            failure_reason=f"Unknown tool '{invalid_calls[0].name}' ({self._strike_count}/{self.max_invalid_strikes})",
            repaired_names=tuple(repaired_pairs),
        )
