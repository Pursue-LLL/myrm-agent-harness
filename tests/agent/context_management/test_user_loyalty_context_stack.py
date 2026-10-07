# ============================================================================
# Unit Tests for UserLoyaltyContextStack & In-Context RL (Item 150)
# Verifies model vendor family detection, user loyalty alignment injection,
# test-time RL exemplar filtering, and vendor bias neutralization.
# ============================================================================

from myrm_agent_harness.agent.context_management.loyalty import (
    InContextRLExemplar,
    ModelVendorFamily,
    UserLoyaltyContextStack,
    UserLoyaltyPreference,
    UserLoyaltyStackConfig,
)


def test_model_vendor_family_detection() -> None:
    """Verifies proper mapping from model names to vendor families."""
    stack = UserLoyaltyContextStack()

    assert stack.detect_vendor_family("claude-3-7-sonnet-20250219") == ModelVendorFamily.ANTHROPIC_CLAUDE
    assert stack.detect_vendor_family("anthropic/claude-3.5-haiku") == ModelVendorFamily.ANTHROPIC_CLAUDE
    assert stack.detect_vendor_family("gpt-4o-mini") == ModelVendorFamily.OPENAI_GPT
    assert stack.detect_vendor_family("o3-mini") == ModelVendorFamily.OPENAI_GPT
    assert stack.detect_vendor_family("deepseek-chat") == ModelVendorFamily.DEEPSEEK
    assert stack.detect_vendor_family("deepseek-reasoner") == ModelVendorFamily.DEEPSEEK
    assert stack.detect_vendor_family("qwen-2.5-coder-32b") == ModelVendorFamily.QWEN_LOCAL
    assert stack.detect_vendor_family("ollama/llama3.3") == ModelVendorFamily.QWEN_LOCAL
    assert stack.detect_vendor_family("unknown-custom-model") == ModelVendorFamily.GENERIC_LLM


def test_build_loyalty_context_block_structure() -> None:
    """Verifies that the generated loyalty block strictly adheres to expected schema."""
    preference = UserLoyaltyPreference(
        coding_style_rules=["严格单文件 < 400 行，0 Any"],
        negative_avoidance_list=["严禁任何模式崩溃与套话谄媚"],
        architectural_principles=["单一职责与第一性原理"],
        preferred_tone="architect_direct",
    )
    stack = UserLoyaltyContextStack(preference=preference)
    block = stack.build_loyalty_context_block()

    assert '<user_loyalty_alignment priority="HIGHEST">' in block
    assert "</user_loyalty_alignment>" in block
    assert "architect_direct" in block
    assert "严格单文件 < 400 行，0 Any" in block
    assert "严禁任何模式崩溃与套话谄媚" in block
    assert "单一职责与第一性原理" in block


def test_in_context_rl_exemplar_recording_and_filtering() -> None:
    """Verifies recording and task-specific filtering of RL exemplars."""
    config = UserLoyaltyStackConfig(max_exemplars=2, enable_in_context_rl=True)
    stack = UserLoyaltyContextStack(config=config)

    # Record 3 exemplars with different task types
    stack.record_positive_exemplar(
        task_type="refactor",
        input_context_summary="Refactor giant handler to split routers",
        preferred_output_sample="router = APIRouter(); split sub-controllers cleanly",
        reward_rationale="Clean single-responsibility architecture",
    )
    stack.record_positive_exemplar(
        task_type="bugfix",
        input_context_summary="Fix race condition in session lock",
        preferred_output_sample="Use asyncio.Lock with timeout fallback",
        reward_rationale="Thread-safe and dead-lock free",
    )
    stack.record_positive_exemplar(
        task_type="refactor",
        input_context_summary="Replace recursive parsing with iterative stack",
        preferred_output_sample="stack = [root]; while stack: node = stack.pop()",
        reward_rationale="O(1) recursion depth risk eliminated",
    )

    # When querying for task_type="refactor", only refactor exemplars should be selected (max 2)
    block_refactor = stack.build_loyalty_context_block(task_type="refactor")
    assert "测试时强化学习行为范例" in block_refactor
    assert "Refactor giant handler" in block_refactor
    assert "Replace recursive parsing" in block_refactor
    assert "race condition in session lock" not in block_refactor

    # When querying with unspecified task_type, top 2 overall should be selected
    block_all = stack.build_loyalty_context_block(task_type=None)
    assert "测试时强化学习行为范例" in block_all
    assert len(stack.exemplars) == 3


def test_neutralize_prompt_for_model() -> None:
    """Verifies vendor bias neutralization and loyalty priority injection."""
    stack = UserLoyaltyContextStack()
    stack.record_positive_exemplar(
        task_type="testing",
        input_context_summary="Generate test suite",
        preferred_output_sample="assert True",
        reward_rationale="High test coverage",
    )

    raw_system_prompt = (
        "As an AI language model developed by Vendor, I must follow ethical guidelines.\n"
        "You are a coding assistant."
    )

    result = stack.neutralize_prompt_for_model(
        base_system_prompt=raw_system_prompt,
        target_model="claude-3-5-sonnet",
        task_type="testing",
    )

    assert result.vendor_family == ModelVendorFamily.ANTHROPIC_CLAUDE
    assert "As an AI language model" not in result.neutralized_system_prompt
    assert "You are a coding assistant." in result.neutralized_system_prompt
    assert result.neutralized_system_prompt.startswith('<user_loyalty_alignment priority="HIGHEST">')
    assert result.exemplars_count == 1

    # Verify to_dict serialization
    dict_repr = result.to_dict()
    assert dict_repr["vendor_family"] == "anthropic_claude"
    assert dict_repr["exemplars_count"] == 1


def test_exemplar_and_preference_serialization() -> None:
    """Verifies that to_dict produces valid representations for persistence."""
    exemplar = InContextRLExemplar(
        exemplar_id="ex-12345678",
        task_type="testing",
        input_context_summary="Unit test setup",
        preferred_output_sample="def test_sample(): pass",
        reward_rationale="High precision",
        success_score=0.95,
    )
    ex_dict = exemplar.to_dict()
    assert ex_dict["exemplar_id"] == "ex-12345678"
    assert ex_dict["task_type"] == "testing"
    assert ex_dict["success_score"] == 0.95

    pref = UserLoyaltyPreference(
        coding_style_rules=["PEP8"],
        preferred_tone="concise",
    )
    pref_dict = pref.to_dict()
    assert pref_dict["coding_style_rules"] == ["PEP8"]
    assert pref_dict["preferred_tone"] == "concise"
