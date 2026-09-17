"""Unit tests for the deterministic pre-send context pressure gate."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.streaming.recovery.context_pressure_gate import (
    CONTEXT_OVERFLOW_TERMINAL_CODE,
    ContextPressureConfig,
    estimate_request_tokens,
    is_presumed_overflow,
    preflight_budget,
    presumed_budget,
    resolve_effective_config,
    run_preflight_compact,
)


class _Generic400Error(Exception):
    status_code = 400


def _messages(n: int) -> list:
    out: list = []
    for i in range(n):
        out.append(HumanMessage(content=f"question {i} " + "x" * 200))
        out.append(AIMessage(content=f"answer {i} " + "y" * 200))
    return out


def test_config_resolve_defaults_on_missing() -> None:
    cfg = ContextPressureConfig.resolve(None)
    assert cfg.max_context_tokens == 200_000
    assert preflight_budget(cfg) == 160_000


def test_config_resolve_clamps_invalid() -> None:
    cfg = ContextPressureConfig.resolve({"context_pressure_config": {"max_context_tokens": -1}})
    assert cfg.max_context_tokens == 200_000


def test_config_resolve_custom_mapping() -> None:
    cfg = ContextPressureConfig.resolve(
        {"context_pressure_config": {"max_context_tokens": 100_000, "preflight_ratio": 0.5}}
    )
    assert preflight_budget(cfg) == 50_000
    assert presumed_budget(cfg) == 85_000


def test_effective_config_prefers_explicit_mapping() -> None:
    llm = SimpleNamespace(max_input_tokens=1_000_000)
    cfg = resolve_effective_config({"context_pressure_config": {"max_context_tokens": 50_000}}, llm)
    assert cfg.max_context_tokens == 50_000


def test_effective_config_uses_model_window() -> None:
    llm = SimpleNamespace(max_input_tokens=1_000_000)
    cfg = resolve_effective_config(None, llm)
    assert cfg.max_context_tokens == 1_000_000
    assert preflight_budget(cfg) == 800_000


def test_effective_config_falls_back_to_default() -> None:
    cfg = resolve_effective_config(None, SimpleNamespace())
    assert cfg.max_context_tokens == 200_000


def test_terminal_code_is_stable() -> None:
    assert CONTEXT_OVERFLOW_TERMINAL_CODE == "context_overflow_after_compaction"


def test_presumed_overflow_matches_generic_400_at_high_occupancy() -> None:
    cfg = ContextPressureConfig(max_context_tokens=1_000)
    exc: Exception = _Generic400Error("The request contains invalid parameters.")
    assert is_presumed_overflow(exc, 900, cfg) is True
    assert is_presumed_overflow(exc, 100, cfg) is False


def test_presumed_overflow_rejects_non_400() -> None:
    class _E500Error(Exception):
        status_code = 500

    cfg = ContextPressureConfig(max_context_tokens=1_000)
    assert is_presumed_overflow(_E500Error("overloaded"), 999, cfg) is False


def test_presumed_overflow_rejects_explicit_overflow_signal() -> None:
    class _E400Error(Exception):
        status_code = 400

    cfg = ContextPressureConfig(max_context_tokens=1_000)
    exc: Exception = _E400Error("maximum context length exceeded")
    assert is_presumed_overflow(exc, 999, cfg) is False


async def test_preflight_compact_sheds_without_llm() -> None:
    messages = _messages(6)
    before = estimate_request_tokens(messages)
    assert before > 0
    saved, strategy = await run_preflight_compact(messages)
    assert saved > 0
    assert strategy in ("context_preflight_compact", "context_preflight_truncation")
    after = estimate_request_tokens(messages)
    assert after < before
