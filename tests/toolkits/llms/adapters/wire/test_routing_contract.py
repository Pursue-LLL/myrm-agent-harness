"""Contract tests mirroring server wire registry patterns."""

from __future__ import annotations

import re

from myrm_agent_harness.core.config.wire import DEFAULT_WIRE_PROTOCOL

_MUSE_SPARK_PATTERN = re.compile(r"^muse-spark", re.IGNORECASE)
_GPT_PATTERN = re.compile(r"^gpt-", re.IGNORECASE)
_GROK_PATTERN = re.compile(r"^grok-", re.IGNORECASE)
_MINIMAX_PATTERN = re.compile(r"^minimax-", re.IGNORECASE)
_QWEN_PATTERN = re.compile(r"^qwen", re.IGNORECASE)

_WIRE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (_MUSE_SPARK_PATTERN, "responses"),
    (_GPT_PATTERN, "responses"),
    (_GROK_PATTERN, "responses"),
    (_MINIMAX_PATTERN, "anthropic_messages"),
    (_QWEN_PATTERN, "anthropic_messages"),
)

_OPENCODE_BASE = "https://opencode.ai/zen/go/v1"


def _is_opencode_endpoint(base_url: str | None) -> bool:
    if not base_url:
        return False
    normalized = base_url.strip().lower()
    return "opencode.ai" in normalized or "localhost:20128" in normalized


def _normalize_model_name_for_wire(model: str) -> str:
    name = model.rsplit("/", 1)[-1] if "/" in model else model
    if name.endswith("-free") and "muse-spark" in name.lower():
        name = name[: -len("-free")]
    return name


def _resolve_wire_protocol(
    model: str,
    base_url: str | None = None,
    *,
    provider_id: str | None = None,
) -> str:
    if provider_id == "opencode_go":
        scoped = True
    elif not _is_opencode_endpoint(base_url):
        scoped = False
    else:
        scoped = True
    if not scoped:
        return DEFAULT_WIRE_PROTOCOL
    normalized = _normalize_model_name_for_wire(model)
    for pattern, wire in _WIRE_RULES:
        if pattern.search(normalized):
            return wire
    return DEFAULT_WIRE_PROTOCOL


def test_muse_spark_responses() -> None:
    assert _resolve_wire_protocol("openai/muse-spark-1.2-contributor", _OPENCODE_BASE) == "responses"


def test_gpt_luna_responses() -> None:
    assert _resolve_wire_protocol("openai/gpt-5.6-luna", _OPENCODE_BASE) == "responses"


def test_grok_responses() -> None:
    assert _resolve_wire_protocol("openai/grok-4.6", _OPENCODE_BASE) == "responses"


def test_minimax_anthropic_messages() -> None:
    assert _resolve_wire_protocol("openai/minimax-m2", _OPENCODE_BASE) == "anthropic_messages"


def test_qwen_not_routed_off_opencode() -> None:
    assert _resolve_wire_protocol("openai/qwen-max", "https://api.example.com/v1") == "chat_completions"


def test_deepseek_chat_completions() -> None:
    assert _resolve_wire_protocol("openai/deepseek-v4-flash", _OPENCODE_BASE) == "chat_completions"


def test_muse_spark_via_provider_id_on_proxy() -> None:
    assert (
        _resolve_wire_protocol(
            "openai/muse-spark-1.2-contributor",
            "https://proxy.example.com/v1",
            provider_id="opencode_go",
        )
        == "responses"
    )
