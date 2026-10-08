"""Unit tests for Local LLM Long-Context Prefill Latency Guard and Adaptive Pruning Suite.

Validates endpoint introspection, polynomial TTFT estimation, adaptive pruning decisioning,
end-to-end message compaction, and WebUI progress capsule generation.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.local_prefill_guard import (
    AdaptivePruningDecision,
    LatencyWarningLevel,
    LocalAdaptivePruningScheduler,
    LocalEndpointInspector,
    LocalEndpointKind,
    LocalEndpointProfile,
    LocalPrefillGuardResult,
    LocalPrefillGuardSuite,
    PrefillLatencyEstimate,
    PrefillProgressCapsule,
    PruningPolicyTier,
    TtftLatencyEstimator,
)


def test_endpoint_introspection_and_profiling() -> None:
    """Verify endpoint introspection across Ollama, MLX, vLLM, and cloud configurations."""
    # 1. Ollama local endpoint
    ollama_prof = LocalEndpointInspector.inspect(
        base_url="http://localhost:11434/v1",
        model_name="qwen2.5-coder:14b-instruct-q4_k_m",
    )
    assert ollama_prof.is_local is True
    assert ollama_prof.endpoint_kind == LocalEndpointKind.OLLAMA
    assert ollama_prof.estimated_param_size_b == 14.0
    assert ollama_prof.quantization == "q4_k_m"

    # 2. Local 70B model on MLX
    mlx_prof = LocalEndpointInspector.inspect(
        base_url="http://127.0.0.1:8080/v1",
        provider="mlx-lm",
        model_name="deepseek-r1-distill-llama-70b-q8",
    )
    assert mlx_prof.is_local is True
    assert mlx_prof.endpoint_kind == LocalEndpointKind.MLX
    assert mlx_prof.estimated_param_size_b == 70.0
    assert mlx_prof.quantization == "q8_0"

    # 3. Cloud API endpoint
    cloud_prof = LocalEndpointInspector.inspect(
        base_url="https://api.anthropic.com/v1",
        model_name="claude-3-5-sonnet-20241022",
    )
    assert cloud_prof.is_local is False
    assert cloud_prof.endpoint_kind == LocalEndpointKind.CLOUD_API


def test_quadratic_ttft_latency_estimation() -> None:
    """Verify polynomial TTFT scaling and freeze warning boundaries for local models."""
    local_70b = LocalEndpointProfile(
        endpoint_kind=LocalEndpointKind.OLLAMA,
        model_name="llama3.3:70b",
        is_local=True,
        estimated_param_size_b=70.0,
        memory_bandwidth_gb_s=400.0,
    )

    # Small context: 4k tokens -> Normal latency
    est_4k = TtftLatencyEstimator.estimate_ttft(4000, local_70b)
    assert est_4k.warning_level in (LatencyWarningLevel.NORMAL, LatencyWarningLevel.ELEVATED)
    assert est_4k.suggests_aggressive_pruning is False

    # Mid-large context: 32k tokens -> Critical slow prefill warning
    est_32k = TtftLatencyEstimator.estimate_ttft(32000, local_70b)
    assert est_32k.estimated_ttft_seconds >= 15.0
    assert est_32k.warning_level in (LatencyWarningLevel.CRITICAL_SLOW, LatencyWarningLevel.FREEZE_RISK)
    assert est_32k.suggests_aggressive_pruning is True

    # Extreme context: 64k tokens -> Freeze risk (reproducing Viticci / @sabastod 118s stall)
    est_64k = TtftLatencyEstimator.estimate_ttft(64000, local_70b)
    assert est_64k.estimated_ttft_seconds >= 60.0
    assert est_64k.warning_level == LatencyWarningLevel.FREEZE_RISK
    assert est_64k.suggests_aggressive_pruning is True
    assert est_64k.quadratic_overhead_fraction > 0.3


def test_adaptive_pruning_decision_tiers() -> None:
    """Verify policy tier switching from conservative cloud to aggressive local thresholds."""
    cloud_profile = LocalEndpointProfile(
        endpoint_kind=LocalEndpointKind.CLOUD_API,
        model_name="gpt-4o",
        is_local=False,
    )
    local_profile = LocalEndpointProfile(
        endpoint_kind=LocalEndpointKind.VLLM,
        model_name="qwen2.5-32b",
        is_local=True,
        estimated_param_size_b=32.0,
    )

    # Cloud target maintains standard 2048 threshold
    dec_cloud = LocalAdaptivePruningScheduler.compute_decision(35000, cloud_profile)
    assert dec_cloud.policy_tier == PruningPolicyTier.CONSERVATIVE_CLOUD
    assert dec_cloud.threshold_tokens == 2048
    assert dec_cloud.keep_recent_calls == 5

    # Local at 8k tokens adopts balanced tier
    dec_local_8k = LocalAdaptivePruningScheduler.compute_decision(8000, local_profile)
    assert dec_local_8k.policy_tier == PruningPolicyTier.BALANCED_LOCAL
    assert dec_local_8k.threshold_tokens == 1024
    assert dec_local_8k.keep_recent_calls == 3

    # Local at 32k tokens adopts aggressive tier (down to 512 tokens)
    dec_local_32k = LocalAdaptivePruningScheduler.compute_decision(32000, local_profile)
    assert dec_local_32k.policy_tier == PruningPolicyTier.AGGRESSIVE_LOCAL_32K
    assert dec_local_32k.threshold_tokens == 512
    assert dec_local_32k.keep_recent_calls == 2

    # Local at 64k tokens adopts emergency shedding tier (down to 256 tokens)
    dec_local_64k = LocalAdaptivePruningScheduler.compute_decision(64000, local_profile)
    assert dec_local_64k.policy_tier == PruningPolicyTier.EMERGENCY_SHEDDING
    assert dec_local_64k.threshold_tokens == 256
    assert dec_local_64k.keep_recent_calls == 1


def test_end_to_end_local_guard_and_pruning_flow() -> None:
    """Verify end-to-end execution: message compaction, latency reduction, and progress capsule."""
    large_html_output = "<html><body><h1>Search Results</h1><p>" + ("long data table row content. " * 300) + "</p></body></html>"
    large_log_output = "Error Trace:\n" + ("2026-10-08 INFO trace entry log line item detail\n" * 250) + "Panic: heap corrupted"
    build_output = "Build passed: 42 modules compiled successfully."
    recent_active_output = "status: active command completed successfully."

    # Construct conversation with 4 tool outputs: first 2 are older consumed, last 2 are recent
    messages = [
        HumanMessage(content="Analyze repository logs and crawl documentation."),
        AIMessage(content="Crawling documentation now..."),
        ToolMessage(content=large_html_output, name="web_search", tool_call_id="call_001"),
        AIMessage(content="Analyzing search results. Now inspecting server logs..."),
        ToolMessage(content=large_log_output, name="read_logs", tool_call_id="call_002"),
        AIMessage(content="Logs reviewed. Now running build..."),
        ToolMessage(content=build_output, name="run_build", tool_call_id="call_003"),
        AIMessage(content="Build finished. Now executing recent verification tool..."),
        ToolMessage(content=recent_active_output, name="run_check", tool_call_id="call_004"),
    ]

    local_profile = LocalEndpointProfile(
        endpoint_kind=LocalEndpointKind.OLLAMA,
        model_name="qwen2.5-coder:32b",
        is_local=True,
        estimated_param_size_b=32.0,
    )

    # Execute guard and prune with forced aggressive flag (threshold=512, keep_recent=2)
    pruned_msgs, result = LocalPrefillGuardSuite.guard_and_prune(
        messages,
        profile=local_profile,
        force_aggressive=True,
    )

    assert isinstance(result, LocalPrefillGuardResult)
    assert result.tokens_saved > 0
    assert result.final_tokens < result.original_tokens
    assert len(result.pruned_summaries) >= 2

    # Verify tool outputs: first consumed tool output is replaced with compact form
    assert isinstance(pruned_msgs[2], ToolMessage)
    assert "Local Prefill Guard: Pruned web_search output" in str(pruned_msgs[2].content)

    # Verify key finding is retained from the panic log in the second tool output
    assert isinstance(pruned_msgs[4], ToolMessage)
    assert "Local Prefill Guard: Pruned read_logs output" in str(pruned_msgs[4].content)
    assert "Key finding:" in str(pruned_msgs[4].content)

    # Verify the most recent tool outputs were retained intact (keep_recent=2)
    assert str(pruned_msgs[6].content) == build_output
    assert str(pruned_msgs[8].content) == recent_active_output

    # Verify progress capsule generated for WebUI transparency
    capsule = result.capsule
    assert isinstance(capsule, PrefillProgressCapsule)
    assert capsule.capsule_id.startswith("prefill-capsule-")
    assert capsule.tokens_before_prune == result.original_tokens
    assert capsule.tokens_after_prune == result.final_tokens
    assert capsule.estimated_latency_saved_seconds >= 0.0

    # Verify pipeline processor kwargs bridge
    kwargs = LocalPrefillGuardSuite.derive_pipeline_processor_args(local_profile, 35000)
    assert kwargs["threshold_tokens"] == 512
    assert kwargs["keep_recent_calls"] == 2
    assert "local_guard:" in str(kwargs["prune_reason"])
