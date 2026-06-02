"""model_discipline.py unit tests

Covers all public/internal functions and constants:
- AGENT_CORE_RULES constant structure
- _extract_model_name: model name extraction from LLM instances
- _should_enforce: family matching for tool-use enforcement
- _get_family_discipline: per-family discipline resolution
- resolve_execution_discipline: full 3-layer composition
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.agent.streaming.model_discipline import (
    _CHINESE_MODEL_DISCIPLINE,
    _CLAUDE_DISCIPLINE,
    _ENFORCEMENT_FAMILIES,
    _ESCALATION_CONTRACT_TEMPLATE,
    _GEMINI_DISCIPLINE,
    _GPT_DISCIPLINE,
    _TOOL_ENFORCEMENT,
    AGENT_CORE_RULES,
    _extract_model_name,
    _get_family_discipline,
    _should_enforce,
    resolve_escalation_contract,
    resolve_execution_discipline,
)


def _make_llm(
    model_name: str | None = None, model: str | None = None
) -> BaseChatModel:
    """Create a mock LLM with configurable model_name / model attributes."""
    llm = MagicMock(spec=BaseChatModel)
    if model_name is not None:
        llm.model_name = model_name
    else:
        del llm.model_name
    if model is not None:
        llm.model = model
    else:
        del llm.model
    return llm


# ============================================================================
# AGENT_CORE_RULES constant
# ============================================================================


class TestAgentCoreRules:
    def test_wrapped_in_xml_tags(self) -> None:
        assert AGENT_CORE_RULES.startswith("\n<agent_behavior_rules>")
        assert AGENT_CORE_RULES.endswith("</agent_behavior_rules>")

    def test_anti_narration_present(self) -> None:
        assert "NEVER narrate" in AGENT_CORE_RULES

    def test_tool_honesty_present(self) -> None:
        assert "NEVER fabricate" in AGENT_CORE_RULES

    def test_anti_negative_claim_present(self) -> None:
        assert "Negative claims" in AGENT_CORE_RULES

    def test_anti_negative_claim_requires_verification(self) -> None:
        assert "verification tool" in AGENT_CORE_RULES

    def test_anti_negative_claim_evidence_required(self) -> None:
        assert "tool name and" in AGENT_CORE_RULES
        assert "query as evidence" in AGENT_CORE_RULES

    def test_anti_negative_claim_no_tool_fallback(self) -> None:
        assert "I have not verified this" in AGENT_CORE_RULES

    def test_xml_tool_call_defense_present(self) -> None:
        assert "<tool_call>" in AGENT_CORE_RULES
        assert "Function Calling API" in AGENT_CORE_RULES

    def test_context_first_check_present(self) -> None:
        assert "conversation context" in AGENT_CORE_RULES
        assert "redundant tool calls" in AGENT_CORE_RULES.lower()

    def test_is_re_exported_as_agent_behavior_rules(self) -> None:
        from myrm_agent_harness.agent.streaming.utils import AGENT_BEHAVIOR_RULES

        assert AGENT_BEHAVIOR_RULES is AGENT_CORE_RULES


# ============================================================================
# _TOOL_ENFORCEMENT constant
# ============================================================================


class TestToolEnforcement:
    def test_wrapped_in_xml_tags(self) -> None:
        assert "<tool_use_enforcement>" in _TOOL_ENFORCEMENT
        assert "</tool_use_enforcement>" in _TOOL_ENFORCEMENT

    def test_must_use_tools(self) -> None:
        assert "You MUST use your tools" in _TOOL_ENFORCEMENT


# ============================================================================
# _extract_model_name
# ============================================================================


class TestExtractModelName:
    def test_uses_model_name_attr(self) -> None:
        llm = _make_llm(model_name="GPT-4o")
        assert _extract_model_name(llm) == "gpt-4o"

    def test_falls_back_to_model_attr(self) -> None:
        llm = _make_llm(model="Claude-3.5-Sonnet")
        assert _extract_model_name(llm) == "claude-3.5-sonnet"

    def test_model_name_takes_precedence(self) -> None:
        llm = _make_llm(model_name="GPT-4o", model="claude-3")
        assert _extract_model_name(llm) == "gpt-4o"

    def test_empty_model_name_falls_back(self) -> None:
        llm = _make_llm(model_name="", model="Gemini-2.0")
        assert _extract_model_name(llm) == "gemini-2.0"

    def test_no_attrs_returns_empty(self) -> None:
        llm = _make_llm()
        assert _extract_model_name(llm) == ""

    def test_always_returns_lowercase(self) -> None:
        llm = _make_llm(model_name="DEEPSEEK-R1")
        assert _extract_model_name(llm) == "deepseek-r1"


# ============================================================================
# _should_enforce
# ============================================================================


class TestShouldEnforce:
    @pytest.mark.parametrize("family", list(_ENFORCEMENT_FAMILIES))
    def test_all_known_families_enforce(self, family: str) -> None:
        assert _should_enforce(f"some-{family}-model") is True

    def test_unknown_model_no_enforcement(self) -> None:
        assert _should_enforce("llama-3-70b") is False

    def test_empty_string_no_enforcement(self) -> None:
        assert _should_enforce("") is False

    def test_exact_family_match(self) -> None:
        assert _should_enforce("gpt") is True

    def test_case_sensitive_requires_lower(self) -> None:
        assert _should_enforce("GPT") is False


# ============================================================================
# _get_family_discipline
# ============================================================================


class TestGetFamilyDiscipline:
    @pytest.mark.parametrize("substring", ["gpt", "codex", "grok"])
    def test_gpt_family(self, substring: str) -> None:
        result = _get_family_discipline(f"some-{substring}-v2")
        assert result is _GPT_DISCIPLINE

    @pytest.mark.parametrize("substring", ["gemini", "gemma"])
    def test_gemini_family(self, substring: str) -> None:
        result = _get_family_discipline(f"some-{substring}-v2")
        assert result is _GEMINI_DISCIPLINE

    @pytest.mark.parametrize("substring", ["claude", "anthropic"])
    def test_claude_family(self, substring: str) -> None:
        result = _get_family_discipline(f"some-{substring}-v2")
        assert result is _CLAUDE_DISCIPLINE

    @pytest.mark.parametrize("substring", ["deepseek", "qwen", "glm"])
    def test_chinese_model_family(self, substring: str) -> None:
        result = _get_family_discipline(f"some-{substring}-v2")
        assert result is _CHINESE_MODEL_DISCIPLINE

    def test_unknown_returns_empty(self) -> None:
        assert _get_family_discipline("llama-3-70b") == ""

    def test_empty_returns_empty(self) -> None:
        assert _get_family_discipline("") == ""


# ============================================================================
# resolve_execution_discipline — integration
# ============================================================================


class TestResolveExecutionDiscipline:
    """Full integration tests for the 3-layer composition."""

    def test_gpt_model_all_3_layers(self) -> None:
        llm = _make_llm(model_name="gpt-4o")
        result = resolve_execution_discipline(llm)
        assert AGENT_CORE_RULES in result
        assert _TOOL_ENFORCEMENT in result
        assert _GPT_DISCIPLINE in result
        assert result.startswith(AGENT_CORE_RULES)

    def test_claude_model_all_3_layers(self) -> None:
        llm = _make_llm(model_name="claude-3.5-sonnet")
        result = resolve_execution_discipline(llm)
        assert AGENT_CORE_RULES in result
        assert _TOOL_ENFORCEMENT in result
        assert _CLAUDE_DISCIPLINE in result

    def test_gemini_model_all_3_layers(self) -> None:
        llm = _make_llm(model_name="gemini-2.0-flash")
        result = resolve_execution_discipline(llm)
        assert AGENT_CORE_RULES in result
        assert _TOOL_ENFORCEMENT in result
        assert _GEMINI_DISCIPLINE in result

    def test_deepseek_model_all_3_layers(self) -> None:
        llm = _make_llm(model_name="deepseek-r1")
        result = resolve_execution_discipline(llm)
        assert AGENT_CORE_RULES in result
        assert _TOOL_ENFORCEMENT in result
        assert _CHINESE_MODEL_DISCIPLINE in result

    def test_qwen_model_uses_chinese_discipline(self) -> None:
        llm = _make_llm(model_name="qwen-2.5-coder")
        result = resolve_execution_discipline(llm)
        assert _CHINESE_MODEL_DISCIPLINE in result

    def test_glm_model_uses_chinese_discipline(self) -> None:
        llm = _make_llm(model_name="glm-4-plus")
        result = resolve_execution_discipline(llm)
        assert _CHINESE_MODEL_DISCIPLINE in result

    def test_unknown_model_only_core(self) -> None:
        llm = _make_llm(model_name="llama-3-70b")
        result = resolve_execution_discipline(llm)
        assert result == AGENT_CORE_RULES
        assert _TOOL_ENFORCEMENT not in result
        assert _GPT_DISCIPLINE not in result

    def test_no_model_attrs_only_core(self) -> None:
        llm = _make_llm()
        result = resolve_execution_discipline(llm)
        assert result == AGENT_CORE_RULES

    def test_returns_string(self) -> None:
        llm = _make_llm(model_name="gpt-4o")
        assert isinstance(resolve_execution_discipline(llm), str)

    def test_idempotent_same_model(self) -> None:
        """KV cache safety: same model must produce identical output."""
        llm = _make_llm(model_name="gpt-4o")
        r1 = resolve_execution_discipline(llm)
        r2 = resolve_execution_discipline(llm)
        assert r1 == r2

    def test_different_families_differ(self) -> None:
        gpt = resolve_execution_discipline(_make_llm(model_name="gpt-4o"))
        claude = resolve_execution_discipline(
            _make_llm(model_name="claude-3.5-sonnet")
        )
        assert gpt != claude

    def test_codex_uses_gpt_discipline(self) -> None:
        llm = _make_llm(model_name="codex-mini")
        result = resolve_execution_discipline(llm)
        assert _GPT_DISCIPLINE in result

    def test_grok_uses_gpt_discipline(self) -> None:
        llm = _make_llm(model_name="grok-2")
        result = resolve_execution_discipline(llm)
        assert _GPT_DISCIPLINE in result

    def test_gemma_uses_gemini_discipline(self) -> None:
        llm = _make_llm(model_name="gemma-3-27b")
        result = resolve_execution_discipline(llm)
        assert _GEMINI_DISCIPLINE in result

    def test_anthropic_uses_claude_discipline(self) -> None:
        llm = _make_llm(model_name="anthropic/claude-3-opus")
        result = resolve_execution_discipline(llm)
        assert _CLAUDE_DISCIPLINE in result

    def test_layer_order_correct(self) -> None:
        """Verify layers are concatenated in order: core → enforcement → family."""
        llm = _make_llm(model_name="gpt-4o")
        result = resolve_execution_discipline(llm)
        core_pos = result.index(AGENT_CORE_RULES)
        enf_pos = result.index(_TOOL_ENFORCEMENT)
        disc_pos = result.index(_GPT_DISCIPLINE)
        assert core_pos < enf_pos < disc_pos


# ============================================================================
# Discipline content structure checks
# ============================================================================


class TestDisciplineContentStructure:
    """Verify each discipline constant has proper XML wrapping."""

    def test_gpt_discipline_has_xml_tags(self) -> None:
        assert "<execution_discipline>" in _GPT_DISCIPLINE
        assert "</execution_discipline>" in _GPT_DISCIPLINE
        assert "<tool_persistence>" in _GPT_DISCIPLINE
        assert "<mandatory_tool_use>" in _GPT_DISCIPLINE
        assert "<act_dont_ask>" in _GPT_DISCIPLINE
        assert "<verification>" in _GPT_DISCIPLINE

    def test_gemini_discipline_has_xml_tags(self) -> None:
        assert "<execution_discipline>" in _GEMINI_DISCIPLINE
        assert "</execution_discipline>" in _GEMINI_DISCIPLINE

    def test_claude_discipline_has_xml_tags(self) -> None:
        assert "<execution_discipline>" in _CLAUDE_DISCIPLINE
        assert "</execution_discipline>" in _CLAUDE_DISCIPLINE

    def test_chinese_model_discipline_has_xml_tags(self) -> None:
        assert "<execution_discipline>" in _CHINESE_MODEL_DISCIPLINE
        assert "</execution_discipline>" in _CHINESE_MODEL_DISCIPLINE

    def test_gemini_mentions_absolute_paths(self) -> None:
        assert "absolute file paths" in _GEMINI_DISCIPLINE

    def test_claude_mentions_reduce_disclaimers(self) -> None:
        assert "Minimize disclaimers" in _CLAUDE_DISCIPLINE

    def test_chinese_model_mentions_concise(self) -> None:
        assert "concise" in _CHINESE_MODEL_DISCIPLINE


# ============================================================================
# Edge cases
# ============================================================================


class TestEdgeCases:
    """Edge-case coverage: multi-family names, prefix matching, provider paths."""

    def test_multi_family_string_matches_first(self) -> None:
        """Model name containing multiple families picks the first match."""
        result = _get_family_discipline("gpt-claude-hybrid")
        assert result is _GPT_DISCIPLINE

    def test_family_as_substring_of_word(self) -> None:
        """'gpt' is a substring inside 'chatgpt-4o' — should still match."""
        llm = _make_llm(model_name="chatgpt-4o")
        result = resolve_execution_discipline(llm)
        assert _GPT_DISCIPLINE in result

    def test_provider_slash_prefix(self) -> None:
        """LiteLLM model strings like 'openai/gpt-4o' should match gpt family."""
        llm = _make_llm(model_name="openai/gpt-4o")
        result = resolve_execution_discipline(llm)
        assert _GPT_DISCIPLINE in result

    def test_openai_like_mimo_is_unknown(self) -> None:
        """'openai-like/mimo-v2.5-pro' is not a known family -> only core."""
        llm = _make_llm(model_name="openai-like/mimo-v2.5-pro")
        result = resolve_execution_discipline(llm)
        assert result == AGENT_CORE_RULES

    def test_very_long_model_name(self) -> None:
        """Super-long model name doesn't break anything."""
        llm = _make_llm(model_name="a" * 1000 + "gpt" + "b" * 1000)
        result = resolve_execution_discipline(llm)
        assert _GPT_DISCIPLINE in result

    def test_special_characters_in_name(self) -> None:
        """Unicode / special chars in model name don't raise errors."""
        llm = _make_llm(model_name="模型-test-v1")
        result = resolve_execution_discipline(llm)
        assert result == AGENT_CORE_RULES

    def test_model_via_model_attr_only(self) -> None:
        """model attr path: 'deepseek-chat' via model (not model_name)."""
        llm = _make_llm(model="deepseek-chat")
        result = resolve_execution_discipline(llm)
        assert _CHINESE_MODEL_DISCIPLINE in result

    def test_idempotent_across_separate_llm_instances(self) -> None:
        """Two separate LLM instances with same model name produce identical output."""
        llm1 = _make_llm(model_name="gemini-2.0-flash")
        llm2 = _make_llm(model_name="gemini-2.0-flash")
        assert resolve_execution_discipline(llm1) == resolve_execution_discipline(llm2)

    def test_result_length_varies_by_family(self) -> None:
        """Different families produce outputs of different lengths (GPT longest)."""
        gpt = resolve_execution_discipline(_make_llm(model_name="gpt-4o"))
        claude = resolve_execution_discipline(
            _make_llm(model_name="claude-3.5-sonnet")
        )
        unknown = resolve_execution_discipline(_make_llm(model_name="llama-3"))
        assert len(gpt) > len(claude) > len(unknown)

    def test_enforcement_families_tuple_is_frozen(self) -> None:
        """_ENFORCEMENT_FAMILIES is a tuple (immutable)."""
        assert isinstance(_ENFORCEMENT_FAMILIES, tuple)

    def test_all_enforcement_families_have_discipline(self) -> None:
        """Every family in _ENFORCEMENT_FAMILIES maps to some discipline."""
        for family in _ENFORCEMENT_FAMILIES:
            result = _get_family_discipline(f"test-{family}-v1")
            assert result != "" or not _should_enforce(
                f"test-{family}-v1"
            ), f"Family '{family}' enforces but has no discipline"


# ============================================================================
# resolve_escalation_contract
# ============================================================================


class TestResolveEscalationContract:
    """Tests for the escalation contract prompt injection."""

    def test_no_target_returns_empty(self) -> None:
        llm = _make_llm(model_name="gpt-4o")
        assert resolve_escalation_contract(llm, None) == ""

    def test_same_model_returns_empty(self) -> None:
        llm = _make_llm(model_name="gpt-4o")
        target = _make_llm(model_name="gpt-4o")
        assert resolve_escalation_contract(llm, target) == ""

    def test_different_models_returns_contract(self) -> None:
        llm = _make_llm(model_name="deepseek-v3-flash")
        target = _make_llm(model_name="gpt-4o")
        result = resolve_escalation_contract(llm, target)
        assert "<<<NEEDS_PRO>>>" in result
        assert "deepseek-v3-flash" in result
        assert "gpt-4o" in result

    def test_contract_contains_xml_tags(self) -> None:
        llm = _make_llm(model_name="gpt-4o-mini")
        target = _make_llm(model_name="claude-3.5-sonnet")
        result = resolve_escalation_contract(llm, target)
        assert "<escalation_contract>" in result
        assert "</escalation_contract>" in result

    def test_contract_mentions_sparingly(self) -> None:
        llm = _make_llm(model_name="deepseek-chat")
        target = _make_llm(model_name="deepseek-r1")
        result = resolve_escalation_contract(llm, target)
        assert "sparingly" in result

    def test_empty_model_name_returns_empty(self) -> None:
        llm = _make_llm(model_name="")
        target = _make_llm(model_name="gpt-4o")
        assert resolve_escalation_contract(llm, target) == ""

    def test_empty_target_name_returns_empty(self) -> None:
        llm = _make_llm(model_name="gpt-4o")
        target = _make_llm(model_name="")
        assert resolve_escalation_contract(llm, target) == ""

    def test_idempotent(self) -> None:
        """KV cache safety: same inputs produce identical output."""
        llm = _make_llm(model_name="deepseek-v3-flash")
        target = _make_llm(model_name="gpt-4o")
        r1 = resolve_escalation_contract(llm, target)
        r2 = resolve_escalation_contract(llm, target)
        assert r1 == r2

    def test_template_uses_format_correctly(self) -> None:
        assert "{current_model}" in _ESCALATION_CONTRACT_TEMPLATE
        assert "{target_model}" in _ESCALATION_CONTRACT_TEMPLATE
