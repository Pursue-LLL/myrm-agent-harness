"""Unit tests for Conversational Multi-Specialist Summoning & Context Aggregation (Item 54).

Validates default specialist catalog, @-mention detection, implicit keyword intent sensing,
sandbox-isolated specialist execution, and structured aggregation card bridging.
"""

import pytest

from myrm_agent_harness.agent.sub_agents.specialist_summoning import (
    AggregationCardType,
    SpecialistDomain,
    SpecialistProfile,
    SpecialistSummoningCoordinator,
    SummonExecutionStatus,
    SummonRequest,
    SummonTriggerSource,
)


def test_default_catalog_initialization() -> None:
    """Verifies standard default specialist catalog contains 5 specialized experts."""
    coordinator = SpecialistSummoningCoordinator()
    catalog = coordinator.get_catalog()
    assert len(catalog) == 5

    domains = {p.domain for p in catalog}
    assert SpecialistDomain.COPYWRITING_POLISH in domains
    assert SpecialistDomain.VISUAL_DESIGN in domains
    assert SpecialistDomain.CODE_AUDIT in domains
    assert SpecialistDomain.MARKET_RESEARCH in domains
    assert SpecialistDomain.DATA_ANALYSIS in domains

    humanize = coordinator.get_specialist("specialist_humanize")
    assert humanize is not None
    assert humanize.mention_tag == "@去AI味专家"
    assert len(humanize.suggested_keywords) > 0


def test_explicit_mention_detection() -> None:
    """Verifies extraction of explicit @-mention tag and cleanup of instruction."""
    coordinator = SpecialistSummoningCoordinator()
    user_msg = "@去AI味专家 帮我把这段文案润色得更地道一些，去掉所有AI说教腔"

    result = coordinator.detect_mention_or_intent(user_msg)
    assert result is not None
    profile, source, instruction = result

    assert profile.specialist_id == "specialist_humanize"
    assert source == SummonTriggerSource.EXPLICIT_MENTION
    assert instruction == "帮我把这段文案润色得更地道一些，去掉所有AI说教腔"


def test_implicit_intent_keyword_detection() -> None:
    """Verifies implicit intent detection when user does not write @ tag but mentions keywords."""
    coordinator = SpecialistSummoningCoordinator()
    user_msg = "文章写完了，现在需要根据文意出一套配图设计方案和封面图"

    result = coordinator.detect_mention_or_intent(user_msg)
    assert result is not None
    profile, source, instruction = result

    assert profile.specialist_id == "specialist_visual"
    assert source == SummonTriggerSource.INTENT_DETECTION
    assert instruction == user_msg


def test_empty_or_unmatched_message_detection() -> None:
    """Verifies detection returns None for empty or generic messages with no keyword match."""
    coordinator = SpecialistSummoningCoordinator()
    assert coordinator.detect_mention_or_intent("") is None
    assert coordinator.detect_mention_or_intent("   ") is None
    assert coordinator.detect_mention_or_intent("明天天气怎么样") is None


def test_execute_isolated_specialist_success() -> None:
    """Verifies executing specialist in isolated sandbox produces structured aggregation card."""
    coordinator = SpecialistSummoningCoordinator()
    request = SummonRequest(
        summon_id="summon-audit-001",
        chat_id="chat-test-01",
        specialist_id="specialist_code_audit",
        trigger_source=SummonTriggerSource.EXPLICIT_MENTION,
        instruction="检查以下 SQL 查询是否存在 SQL 注入风险",
        parent_context_slice="SELECT * FROM users WHERE name = " + "name",
    )

    execution = coordinator.execute_isolated_specialist(request)
    assert execution.status == SummonExecutionStatus.COMPLETED
    assert execution.specialist_id == "specialist_code_audit"
    assert execution.aggregation_card is not None

    card = execution.aggregation_card
    assert card.card_id == "card-summon-audit-001"
    assert card.card_type == AggregationCardType.AUDIT_VERDICT
    assert "代码与安全审计专家" in card.specialist_name
    assert len(card.artifacts) == 1
    assert "deliverable_summon-audit-001_code_audit.json" in card.artifacts[0]


def test_execute_isolated_specialist_not_found() -> None:
    """Verifies execution handles unknown specialist gracefully with FAILED status."""
    coordinator = SpecialistSummoningCoordinator()
    request = SummonRequest(
        summon_id="summon-fail-002",
        chat_id="chat-test-02",
        specialist_id="specialist_unknown_domain",
        trigger_source=SummonTriggerSource.INTENT_DETECTION,
        instruction="Do something impossible",
    )

    execution = coordinator.execute_isolated_specialist(request)
    assert execution.status == SummonExecutionStatus.FAILED
    assert execution.aggregation_card is None
    assert "not found" in (execution.error_message or "")


def test_aggregate_to_parent_stream_contract() -> None:
    """Verifies bridging aggregation card to parent stream succeeds on completed runs and raises on failure."""
    coordinator = SpecialistSummoningCoordinator()
    request = SummonRequest(
        summon_id="summon-market-003",
        chat_id="chat-test-03",
        specialist_id="specialist_market_research",
        trigger_source=SummonTriggerSource.EXPLICIT_MENTION,
        instruction="对比 Notion AI 与 Cursor 的产品定位与商业模式",
    )

    execution = coordinator.execute_isolated_specialist(request)
    card = coordinator.aggregate_to_parent_stream(execution)
    assert card.card_type == AggregationCardType.RESEARCH_REPORT
    assert "竞品与商业洞察分析师" in card.headline

    # Failure case
    execution.status = SummonExecutionStatus.FAILED
    execution.aggregation_card = None
    with pytest.raises(ValueError, match="Cannot aggregate incomplete execution"):
        coordinator.aggregate_to_parent_stream(execution)


def test_custom_specialist_registration() -> None:
    """Verifies registering a custom specialist dynamically."""
    coordinator = SpecialistSummoningCoordinator()
    custom = SpecialistProfile(
        specialist_id="specialist_legal",
        name="法务合规审核员",
        mention_tag="@法务合规员",
        domain=SpecialistDomain.CODE_AUDIT,
        description="专精于开源许可证合规与隐私合规审查",
        system_prompt_addon="Audit license compliance and GDPR policies.",
        suggested_keywords=["法务合规", "开源协议", "GPL检查"],
    )

    coordinator.register_specialist(custom)
    assert coordinator.get_specialist("specialist_legal") is not None

    detection = coordinator.detect_mention_or_intent("@法务合规员 检查此仓库是否有 GPL 污染")
    assert detection is not None
    assert detection[0].specialist_id == "specialist_legal"
    assert detection[2] == "检查此仓库是否有 GPL 污染"
