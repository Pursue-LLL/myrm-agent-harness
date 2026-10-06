"""Raw Model Direct Passthrough and Pristine Testing Sandbox.

Provides zero-injection direct passthrough execution that bypasses framework system prompts
and tool declarations, enabling faithful evaluation of native model personalities,
as well as side-by-side comparative experiments against agent-augmented execution.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from myrm_agent_harness.runtime.context.pristine_passthrough_sandbox_types import (
    DualRunExperimentReport,
    PristineExecutionConfig,
    PristinePassthroughMode,
    PristinePayload,
)

__all__ = [
    "DualRunExperimentReport",
    "PristineExecutionConfig",
    "PristinePassthroughMode",
    "PristinePayload",
    "PristineTestingSandbox",
    "RawModelPassthroughTransformer",
]


class RawModelPassthroughTransformer:
    """Transforms conversational payloads to enforce zero-injection pristine execution."""

    @classmethod
    def transform_for_execution(
        cls,
        *,
        messages: Sequence[dict[str, str]],
        config: PristineExecutionConfig,
        agent_system_prompt: str,
        available_tools: Sequence[dict[str, object]],
    ) -> PristinePayload:
        """Constructs pristine or augmented payload based on configuration directives."""
        if config.mode == PristinePassthroughMode.RAW_PASSTHROUGH:
            filtered_messages: list[dict[str, str]] = []

            # Determine system prompt in raw mode
            active_system_prompt: str | None = None
            if not config.strip_agent_system_prompt:
                active_system_prompt = agent_system_prompt
            elif config.custom_system_prompt is not None:
                active_system_prompt = config.custom_system_prompt

            if active_system_prompt:
                filtered_messages.append({"role": "system", "content": active_system_prompt})

            # Strip existing system messages from input history if stripping is requested
            for m in messages:
                role = m.get("role", "")
                if role == "system" and config.strip_agent_system_prompt:
                    continue
                filtered_messages.append(dict(m))

            return PristinePayload(
                messages=tuple(filtered_messages),
                tools_provided=not config.strip_tools and bool(available_tools),
                system_prompt_used=active_system_prompt,
                is_pristine=True,
            )

        # AGENT_AUGMENTED mode: inject system prompt and full toolset
        augmented_messages: list[dict[str, str]] = []
        if agent_system_prompt:
            augmented_messages.append({"role": "system", "content": agent_system_prompt})

        for m in messages:
            augmented_messages.append(dict(m))

        return PristinePayload(
            messages=tuple(augmented_messages),
            tools_provided=bool(available_tools),
            system_prompt_used=agent_system_prompt if agent_system_prompt else None,
            is_pristine=False,
        )


class PristineTestingSandbox:
    """Orchestrates side-by-side dual-track comparison experiments."""

    @classmethod
    def run_side_by_side_experiment(
        cls,
        *,
        prompt: str,
        raw_runner: Callable[[str], tuple[str, int, float]],
        augmented_runner: Callable[[str], tuple[str, int, int, float]],
        experiment_id: str | None = None,
    ) -> DualRunExperimentReport:
        """Executes raw baseline and agent-augmented tracks, synthesizing comparative metrics.

        `raw_runner` returns: (response_text, token_usage, latency_ms)
        `augmented_runner` returns: (response_text, token_usage, tools_called_count, latency_ms)
        """
        exp_id = experiment_id or f"exp-{int(time.time() * 1000)}"

        # 1. Run raw baseline
        raw_resp, raw_tokens, raw_latency = raw_runner(prompt)

        # 2. Run agent-augmented track
        aug_resp, aug_tokens, tools_count, aug_latency = augmented_runner(prompt)

        # Calculate overhead ratio
        overhead_ratio = aug_tokens / max(raw_tokens, 1)

        return DualRunExperimentReport(
            experiment_id=exp_id,
            prompt=prompt,
            raw_response=raw_resp,
            augmented_response=aug_resp,
            raw_tokens=raw_tokens,
            augmented_tokens=aug_tokens,
            tools_invoked_count=tools_count,
            raw_latency_ms=raw_latency,
            augmented_latency_ms=aug_latency,
            token_overhead_ratio=round(overhead_ratio, 2),
        )
