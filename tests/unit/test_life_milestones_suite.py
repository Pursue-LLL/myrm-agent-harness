"""Unit tests for Life Milestones and Personal Timeline Suite.

Topic 01 Item 137: LifeMilestonesAndPersonalTimelineEngineSuite.
"""

from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.life_milestones import (
    GrowthDiaryEntry,
    LifeMilestone,
    LifeMilestonesSuite,
    LifeStageEra,
    MilestoneCategory,
    MilestoneSignificanceGate,
    PrivacyIntimacyLevel,
    ValueSystemNode,
)


def test_significance_gate_filters_industrial_trivia() -> None:
    gate = MilestoneSignificanceGate(min_significance_threshold=0.70)

    # 1. Industrial chores should be rejected
    res_chore = gate.evaluate(
        title="修复了一个关于 CSS 样式的 bug",
        narrative="修改了按钮的 padding 和颜色，跑了 pytest",
        category=MilestoneCategory.CAREER,
        significance_hint=0.5,
        is_user_explicit=False,
    )
    assert not res_chore.is_admitted
    assert res_chore.rejection_reason is not None
    assert "industrial trivia" in res_chore.rejection_reason

    # 2. Genuine human landmark should be admitted
    res_landmark = gate.evaluate(
        title="大学本科毕业",
        narrative="完成了计算机科学专业的学业，获得学士学位并做出人生新决定",
        category=MilestoneCategory.EDUCATION,
        significance_hint=0.85,
        is_user_explicit=True,
    )
    assert res_landmark.is_admitted
    assert res_landmark.calculated_significance >= 0.70


def test_timeline_engine_chronological_ordering_and_eras() -> None:
    suite = LifeMilestonesSuite()

    # Register Era
    suite.register_era(
        LifeStageEra(
            era_id="era_college",
            label="大学求学探索期",
            start_year=2014,
            end_year=2018,
            guiding_philosophy="广泛阅读，追求纯粹技术与理想主义",
        )
    )
    suite.register_era(
        LifeStageEra(
            era_id="era_startup",
            label="自主创业奋斗期",
            start_year=2019,
            end_year=2023,
            guiding_philosophy="敏捷求存，拥抱风险与坚韧",
        )
    )

    eras = suite.list_eras()
    assert len(eras) == 2
    assert eras[0].era_id == "era_college"
    assert eras[1].era_id == "era_startup"

    # Record milestones
    ok1, _ = suite.record_milestone(
        LifeMilestone(
            milestone_id="ms_2018_grad",
            timestamp_str="2018-06-20",
            year=2018,
            category=MilestoneCategory.EDUCATION,
            title="大学毕业典礼",
            narrative="挥别校园，决定背上行囊奔赴深圳开启首份全职工作",
            long_term_impact="开启经济独立与个人职业长跑",
            core_values=["独立", "探索"],
            significance_score=0.90,
        )
    )
    assert ok1

    ok2, _ = suite.record_milestone(
        LifeMilestone(
            milestone_id="ms_2020_relocate",
            timestamp_str="2020-03-15",
            year=2020,
            category=MilestoneCategory.RELOCATION,
            title="决定定居上海并创立团队",
            narrative="经历了疫情初期的深思，决定移居上海与合伙人创立新项目",
            long_term_impact="重新定义了未来五年的发展重心地理轴心",
            core_values=["长期主义", "拥抱未知"],
            significance_score=0.95,
        )
    )
    assert ok2

    # Query chronological ordering
    all_ms = suite.list_milestones(start_year=2015, end_year=2022)
    assert len(all_ms) == 2
    assert all_ms[0].milestone_id == "ms_2018_grad"
    assert all_ms[1].milestone_id == "ms_2020_relocate"


def test_privacy_intimacy_levels_boundary() -> None:
    suite = LifeMilestonesSuite()

    # Public milestone
    suite.record_milestone(
        LifeMilestone(
            milestone_id="ms_pub",
            timestamp_str="2021-05-01",
            year=2021,
            category=MilestoneCategory.CAREER,
            title="晋升技术合伙人",
            narrative="公开团队晋升与职责拓展",
            long_term_impact="具备公司级技术决策权",
            intimacy_level=PrivacyIntimacyLevel.OPEN_OVERVIEW,
        )
    )

    # Intimate milestone
    suite.record_milestone(
        LifeMilestone(
            milestone_id="ms_intimate",
            timestamp_str="2022-09-10",
            year=2022,
            category=MilestoneCategory.FAMILY_LIFE,
            title="步入婚姻殿堂",
            narrative="与相伴多年的伴侣领证成家",
            long_term_impact="建立家庭避风港，重心开始兼顾家庭陪伴",
            intimacy_level=PrivacyIntimacyLevel.INTIMATE_PERSONAL,
        )
    )

    # Query with OPEN_OVERVIEW boundary
    pub_only = suite.list_milestones(max_intimacy=PrivacyIntimacyLevel.OPEN_OVERVIEW)
    assert len(pub_only) == 1
    assert pub_only[0].milestone_id == "ms_pub"

    # Query with INTIMATE_PERSONAL boundary
    intimate_all = suite.list_milestones(max_intimacy=PrivacyIntimacyLevel.INTIMATE_PERSONAL)
    assert len(intimate_all) == 2


def test_value_system_causal_evolution_and_projection() -> None:
    suite = LifeMilestonesSuite()

    # 1. Initial value
    v1 = ValueSystemNode(
        value_id="val_work_ethic_v1",
        theme="工作生活平衡",
        current_stance="极度推崇全心投入拼搏，相信年轻应当竭尽全力工作",
        effective_since_year=2018,
        is_active=True,
    )
    suite.register_value(v1)

    # 2. Evolve value due to catalyst
    v2 = ValueSystemNode(
        value_id="val_work_ethic_v2",
        theme="工作生活平衡",
        current_stance="健康身心与深度陪伴为第一基石，追求具备可持续节律的高质量创造",
        prior_belief=v1.current_stance,
        transition_catalyst="经历身体健康预警与家庭成员诞生，认识到长跑重在节律而非透支",
        effective_since_year=2022,
        is_active=True,
    )
    suite.evolve_value(v2, prior_node_id=v1.value_id)

    active_vals = suite.list_active_values()
    assert len(active_vals) == 1
    assert active_vals[0].value_id == "val_work_ethic_v2"

    # 3. Project context on philosophical query
    bundle = suite.project_context(
        query_text="最近在考虑换一份节奏适中的工作，感觉有些焦虑和迷茫，不知道怎么抉择",
    )
    assert bundle.relevant_milestone_count >= 0
    assert len(bundle.active_values) == 1
    assert "健康身心与深度陪伴为第一基石" in bundle.projected_text
    assert "注：由早期" in bundle.projected_text
    assert "回复原则" in bundle.projected_text


def test_growth_diary_and_retrospective_card_generation() -> None:
    suite = LifeMilestonesSuite()

    # Record life milestone
    suite.record_milestone(
        LifeMilestone(
            milestone_id="ms_2023_dad",
            timestamp_str="2023-11-08",
            year=2023,
            category=MilestoneCategory.FAMILY_LIFE,
            title="成为一名父亲",
            narrative="女儿平安降生，第一次感受到血脉相连的生命震撼",
            long_term_impact="从此人生多了一份温柔的责任与坚定的铠甲",
            core_values=["家庭", "敬畏生命"],
            significance_score=0.98,
            intimacy_level=PrivacyIntimacyLevel.INTIMATE_PERSONAL,
        )
    )

    # Record diary entry
    suite.record_diary(
        GrowthDiaryEntry(
            entry_id="diary_001",
            timestamp=datetime(2023, 11, 20, 22, 0, tzinfo=UTC),
            emotional_state="静谧祥和",
            reflection_text="看着摇篮里熟睡的宝宝，突然觉得很多世俗的纠结都变得微不足道，内心涌起前所未有的宁静与笃定。",
            linked_milestone_id="ms_2023_dad",
            era_label="成家育儿期",
        )
    )

    diaries = suite.list_diaries()
    assert len(diaries) == 1
    assert diaries[0].emotional_state == "静谧祥和"

    # Generate retrospective card
    card = suite.generate_retrospective_card(
        era_label="成家育儿期",
        start_year=2023,
        end_year=2024,
    )
    assert card.era_label == "成家育儿期"
    assert "成为一名父亲" in card.milestone_highlights[0]
    assert "静谧祥和" in card.growth_reflections[0]
    assert "陪伴并见证这段真实而丰沛的生命历程" in card.companion_empathy_note


def test_suite_telemetry_stats() -> None:
    suite = LifeMilestonesSuite()
    stats = suite.get_stats()
    assert stats["total_milestones"] == 0
    assert stats["total_eras"] == 0
    assert stats["active_values"] == 0
    assert stats["total_diaries"] == 0
