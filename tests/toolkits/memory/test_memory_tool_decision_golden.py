"""Golden decision guardrails for memory_save_tool vs memory_manage_tool prompts.

These tests do not call an LLM. They lock prompt SSOT fragments that steer
tool choice for common memory workflows (aligned with memory_agent_tools.py).
"""

from __future__ import annotations

from dataclasses import dataclass

from myrm_agent_harness.toolkits.memory.agent_surface._memory_agent_tool_descriptions import (
    MEMORY_MANAGE_TOOL_DESCRIPTION_EN,
    MEMORY_MANAGE_TOOL_DESCRIPTION_ZH,
    MEMORY_SAVE_CORE_EN,
    MEMORY_SAVE_CORE_ZH,
    build_memory_save_tool_description,
)
from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import MemorySearchPolicy


@dataclass(frozen=True, slots=True)
class MemoryDecisionScenario:
    scenario_id: str
    expected_tool: str
    save_fragments_en: tuple[str, ...] = ()
    save_fragments_zh: tuple[str, ...] = ()
    manage_fragments_en: tuple[str, ...] = ()
    manage_fragments_zh: tuple[str, ...] = ()
    save_allow_wiki: bool = False
    save_approval_required: bool = False


GOLDEN_MEMORY_DECISIONS: tuple[MemoryDecisionScenario, ...] = (
    MemoryDecisionScenario(
        "explicit_remember",
        "memory_save_tool",
        save_fragments_en=("**WHEN TO SAVE**", '"remember this"'),
        save_fragments_zh=("**何时保存**", "记住这个"),
    ),
    MemoryDecisionScenario(
        "wrong_recalled_fact",
        "memory_manage_tool",
        save_fragments_en=(
            "memory_manage_tool with action=correct",
            "do not save a duplicate",
        ),
        save_fragments_zh=(
            "memory_manage_tool，action=correct",
            "不要重复 save",
        ),
        manage_fragments_en=(
            "correct → knowledge only",
            "use instead of memory_save_tool",
        ),
        manage_fragments_zh=(
            "correct → 仅 knowledge",
            "优先于 memory_save_tool",
        ),
    ),
    MemoryDecisionScenario(
        "session_progress",
        "memory_search_tool",
        save_fragments_en=("memory_search_tool with corpus=sessions",),
        save_fragments_zh=("memory_search_tool，corpus=sessions",),
    ),
    MemoryDecisionScenario(
        "new_preference",
        "memory_save_tool",
        save_fragments_en=("preference:", "preference_key"),
        save_fragments_zh=("preference", "preference_key"),
    ),
    MemoryDecisionScenario(
        "conditional_rule",
        "memory_save_tool",
        save_fragments_en=("rule:", "rule_trigger"),
        save_fragments_zh=("rule", "rule_trigger"),
    ),
    MemoryDecisionScenario(
        "global_instruction",
        "memory_save_tool",
        save_fragments_en=("instruction:", "do not set rule_trigger"),
        save_fragments_zh=("instruction", "不要设置 rule_trigger"),
    ),
    MemoryDecisionScenario(
        "forget_memory",
        "memory_manage_tool",
        manage_fragments_en=('"forget that"', "delete:"),
        manage_fragments_zh=("忘了那个", "delete"),
    ),
    MemoryDecisionScenario(
        "rate_helpful_memory",
        "memory_manage_tool",
        manage_fragments_en=(
            "rate:",
            "rating_score 1-5",
            "rate → knowledge or event only",
        ),
        manage_fragments_zh=(
            "rate",
            "rating_score 1-5",
            "rate → 仅 knowledge 或 event",
        ),
    ),
    MemoryDecisionScenario(
        "wiki_long_document",
        "wiki_ingest_tool",
        save_fragments_en=("wiki_ingest_tool", "document-like content"),
        save_fragments_zh=("wiki_ingest_tool", "文档式内容"),
        save_allow_wiki=True,
    ),
    MemoryDecisionScenario(
        "approval_pending",
        "memory_save_tool",
        save_fragments_en=("submitted for approval",),
        save_fragments_zh=("submitted for approval",),
        save_approval_required=True,
    ),
    MemoryDecisionScenario(
        "duplicate_retry",
        "memory_save_tool",
        save_fragments_en=("Do not retry identical content",),
        save_fragments_zh=("不要用相同内容重试",),
    ),
    MemoryDecisionScenario(
        "third_party_attribution",
        "memory_save_tool",
        save_fragments_en=("NEVER attribute a third party",),
        save_fragments_zh=("绝不要把第三方的特质",),
    ),
    MemoryDecisionScenario(
        "declarative_not_command",
        "memory_save_tool",
        save_fragments_en=(
            "write as declarative facts, not instructions",
            "instruction-style, gets misinterpreted as a command",
            "focused on durable facts",
        ),
        save_fragments_zh=("写陈述性事实，不要写指令", "指令式，易被误解为命令", "聚焦持久事实"),
    ),
    MemoryDecisionScenario(
        "manage_not_for_new_fact",
        "memory_manage_tool",
        manage_fragments_en=("Storing new facts", "memory_save_tool"),
        manage_fragments_zh=("存储新事实", "memory_save_tool"),
    ),
    MemoryDecisionScenario(
        "correct_not_event",
        "memory_manage_tool",
        manage_fragments_en=("correct → knowledge only",),
        manage_fragments_zh=("correct → 仅 knowledge",),
    ),
    MemoryDecisionScenario(
        "instruction_manage_as_rule",
        "memory_manage_tool",
        manage_fragments_en=("instruction saves", "category=rule"),
        manage_fragments_zh=("instruction 保存", "category=rule"),
    ),
)


def _save_description(
    *,
    locale: str,
    allow_wiki: bool = False,
    approval: bool = False,
) -> str:
    return build_memory_save_tool_description(
        MemorySearchPolicy(allow_wiki=allow_wiki),
        approval_required=approval,
        locale=locale,
    )


class TestMemoryToolDecisionGolden:
    def test_golden_catalog_has_sixteen_scenarios(self) -> None:
        assert len(GOLDEN_MEMORY_DECISIONS) == 16

    def test_each_scenario_save_guardrails_en(self) -> None:
        for scenario in GOLDEN_MEMORY_DECISIONS:
            if not scenario.save_fragments_en:
                continue
            text = _save_description(
                locale="en",
                allow_wiki=scenario.save_allow_wiki,
                approval=scenario.save_approval_required,
            )
            for fragment in scenario.save_fragments_en:
                assert fragment in text, f"{scenario.scenario_id}: missing save EN fragment {fragment!r}"

    def test_each_scenario_save_guardrails_zh(self) -> None:
        for scenario in GOLDEN_MEMORY_DECISIONS:
            if not scenario.save_fragments_zh:
                continue
            text = _save_description(
                locale="zh",
                allow_wiki=scenario.save_allow_wiki,
                approval=scenario.save_approval_required,
            )
            for fragment in scenario.save_fragments_zh:
                assert fragment in text, f"{scenario.scenario_id}: missing save ZH fragment {fragment!r}"

    def test_each_scenario_manage_guardrails_en(self) -> None:
        for scenario in GOLDEN_MEMORY_DECISIONS:
            if not scenario.manage_fragments_en:
                continue
            text = MEMORY_MANAGE_TOOL_DESCRIPTION_EN
            for fragment in scenario.manage_fragments_en:
                assert fragment in text, f"{scenario.scenario_id}: missing manage EN fragment {fragment!r}"

    def test_each_scenario_manage_guardrails_zh(self) -> None:
        for scenario in GOLDEN_MEMORY_DECISIONS:
            if not scenario.manage_fragments_zh:
                continue
            text = MEMORY_MANAGE_TOOL_DESCRIPTION_ZH
            for fragment in scenario.manage_fragments_zh:
                assert fragment in text, f"{scenario.scenario_id}: missing manage ZH fragment {fragment!r}"

    def test_save_core_does_not_leak_manage_implementation_details(self) -> None:
        forbidden = ("demotes", "low confidence", "correction memory linked")
        for desc in (MEMORY_SAVE_CORE_EN, MEMORY_SAVE_CORE_ZH):
            for fragment in forbidden:
                assert fragment not in desc

    def test_manage_does_not_leak_implementation_details(self) -> None:
        forbidden = ("demotes", "low confidence", "correction memory linked")
        for desc in (MEMORY_MANAGE_TOOL_DESCRIPTION_EN, MEMORY_MANAGE_TOOL_DESCRIPTION_ZH):
            for fragment in forbidden:
                assert fragment not in desc
