"""Tests for Caveman Ultra-Compact Output Mode and Output Token Throttle Engine."""

from myrm_agent_harness.runtime.context.caveman_output_throttle import (
    AdaptiveThrottleDecisionEngine,
    CavemanOutputPostProcessor,
    CavemanPromptPreamble,
    CavemanThrottleMode,
    ConversationIntentKind,
)


def test_caveman_prompt_preamble():
    preamble = CavemanPromptPreamble.render_preamble()
    assert "<caveman_throttle_preamble>" in preamble
    assert "Eliminate conversational pleasantries" in preamble
    assert "</caveman_throttle_preamble>" in preamble


def test_adaptive_throttle_decision_engine():
    # 1. Mode OFF
    dec_off = AdaptiveThrottleDecisionEngine.decide_throttling(
        mode=CavemanThrottleMode.OFF,
        intent=ConversationIntentKind.EXECUTION_AUTOMATION,
    )
    assert not dec_off.should_inject_preamble
    assert not dec_off.should_strip_pleasantries

    # 2. Mode AGGRESSIVE (applies universally)
    dec_agg = AdaptiveThrottleDecisionEngine.decide_throttling(
        mode=CavemanThrottleMode.AGGRESSIVE,
        intent=ConversationIntentKind.EXPLANATORY_QA,
    )
    assert dec_agg.should_inject_preamble
    assert dec_agg.should_strip_pleasantries

    # 3. Mode EXECUTION_ONLY
    dec_exec = AdaptiveThrottleDecisionEngine.decide_throttling(
        mode=CavemanThrottleMode.EXECUTION_ONLY,
        intent=ConversationIntentKind.TOOL_PIPELINE,
    )
    assert dec_exec.should_inject_preamble
    assert dec_exec.should_strip_pleasantries

    dec_exec_skip = AdaptiveThrottleDecisionEngine.decide_throttling(
        mode=CavemanThrottleMode.EXECUTION_ONLY,
        intent=ConversationIntentKind.EXPLANATORY_QA,
    )
    assert not dec_exec_skip.should_inject_preamble
    assert not dec_exec_skip.should_strip_pleasantries

    # 4. Mode AUTO_ADAPTIVE
    dec_auto_tool = AdaptiveThrottleDecisionEngine.decide_throttling(
        mode=CavemanThrottleMode.AUTO_ADAPTIVE,
        intent=ConversationIntentKind.EXECUTION_AUTOMATION,
    )
    assert dec_auto_tool.should_inject_preamble
    assert dec_auto_tool.should_strip_pleasantries

    dec_auto_qa = AdaptiveThrottleDecisionEngine.decide_throttling(
        mode=CavemanThrottleMode.AUTO_ADAPTIVE,
        intent=ConversationIntentKind.EXPLANATORY_QA,
    )
    assert not dec_auto_qa.should_inject_preamble
    assert not dec_auto_qa.should_strip_pleasantries


def test_caveman_output_post_processor_english():
    raw_response = (
        "Certainly! Here is the bash command to rebuild the container:\n\n"
        "docker compose build --no-cache && docker compose up -d\n\n"
        "Hope this helps! Let me know if you need anything else."
    )

    sanitized = CavemanOutputPostProcessor.sanitize_output(raw_response)

    assert sanitized.sanitized_text == "docker compose build --no-cache && docker compose up -d"
    assert sanitized.stripped_prefix is not None
    assert "Certainly" in sanitized.stripped_prefix
    assert sanitized.stripped_suffix is not None
    assert "Hope this helps" in sanitized.stripped_suffix
    assert sanitized.tokens_saved_estimate > 0


def test_caveman_output_post_processor_chinese():
    raw_response = (
        "好的，没问题，以下是您需要的函数实现：\n"
        "def compute_hash(data: str) -> str:\n"
        "    return hashlib.sha256(data.encode()).hexdigest()\n\n"
        "希望这对您有所帮助！如果有任何问题，请随时告诉我。"
    )

    sanitized = CavemanOutputPostProcessor.sanitize_output(raw_response)

    expected_code = (
        "def compute_hash(data: str) -> str:\n"
        "    return hashlib.sha256(data.encode()).hexdigest()"
    )
    assert sanitized.sanitized_text == expected_code
    assert sanitized.stripped_prefix is not None
    assert "好的，没问题" in sanitized.stripped_prefix
    assert sanitized.stripped_suffix is not None
    assert "希望这对您有所帮助" in sanitized.stripped_suffix
    assert sanitized.tokens_saved_estimate > 0


def test_caveman_output_post_processor_clean_passthrough():
    raw_clean = "pytest tests/unit/test_engine.py -q"
    sanitized = CavemanOutputPostProcessor.sanitize_output(raw_clean)

    assert sanitized.sanitized_text == raw_clean
    assert sanitized.stripped_prefix is None
    assert sanitized.stripped_suffix is None
    assert sanitized.tokens_saved_estimate == 0
