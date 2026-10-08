"""
[INPUT]
myrm_agent_harness.toolkits.memory.two_layer_dialectic (Models, Engines, Orchestrator)

[OUTPUT]
Unit test suite verifying Two-Layer Context Injection & Multi-Pass Dialectic Reconciliation Suite.

[POS]
Harness framework unit tests for Item 112.
Strict typing applied: No `Any` types allowed. Single file < 200 lines.
"""

from myrm_agent_harness.toolkits.memory.two_layer_dialectic import (
    BaseContextEngine,
    DialecticCadenceConfig,
    DialecticReasoningLevel,
    DialecticReconciliationEngine,
    TwoLayerDialecticOrchestrator,
)


def test_base_context_cadence_and_kv_cache_protection() -> None:
    """Verify Layer 1 caches base context across turns and appends to user tail without touching system prompt."""
    config = DialecticCadenceConfig(context_cadence=4)
    engine = BaseContextEngine(config=config)

    # Turn 1: Initial generation
    bundle1 = engine.get_or_generate_bundle(
        session_id="sess_101",
        current_turn=1,
        session_summary="已规划三层架构与强类型规范",
        peer_card_summary="Alice Liu (前端负责人, 严格无Any)",
    )
    assert bundle1.generation_turn == 1
    assert bundle1.system_prompt_frozen is True
    assert bundle1.estimated_tokens > 0

    # Turn 2 & 3: Should reuse cached bundle within cadence window (cadence=4)
    assert not engine.should_refresh_base_context("sess_101", current_turn=2)
    bundle2 = engine.get_or_generate_bundle(
        session_id="sess_101",
        current_turn=2,
        session_summary="已更新部分内容但未到刷新轮次",
        peer_card_summary="Alice Liu",
    )
    assert bundle2.generation_turn == 1  # Unchanged, cached!

    # Turn 5: Exceeded cadence (5 - 1 = 4 >= 4), must refresh
    assert engine.should_refresh_base_context("sess_101", current_turn=5)
    bundle5 = engine.get_or_generate_bundle(
        session_id="sess_101",
        current_turn=5,
        session_summary="更新为完成服务端落地与API集成",
        peer_card_summary="Alice Liu",
    )
    assert bundle5.generation_turn == 5

    # Verify user message tail injection
    user_msg = "请帮我实现两层调和前端控制面板。"
    injected_msg = engine.inject_into_user_message(user_msg, bundle5)
    assert injected_msg.startswith(user_msg)
    assert "<!-- [BASE_CONTEXT_KV_CACHE_PROTECTED] -->" in injected_msg
    assert "<base_context" in injected_msg


def test_dialectic_conflict_detection_and_multi_pass_synthesis() -> None:
    """Verify Layer 2 detects contradictions and executes 1-3 pass dialectic loop."""
    dialectic_engine = DialecticReconciliationEngine(
        default_reasoning_level=DialecticReasoningLevel.DEEP
    )

    history = [
        "团队以往统一使用 SQLite 作为单机轻量数据源",
        "禁止向后兼容，全面进行纯净重构",
    ]
    current_prompt = "在本次生产环境中，我们需要切换至 Postgres 架构以支持分布式扩展"

    conflicts = dialectic_engine.detect_conflicts(history, current_prompt)
    assert len(conflicts) >= 1
    c = conflicts[0]
    assert "数据库" in c.source_topic or "sqlite" in c.prior_stance.lower()
    assert c.severity_score >= 0.8

    # Run full 3-pass dialectic reconciliation
    result = dialectic_engine.reconcile(
        session_id="sess_101",
        turn_index=3,
        conflicts=conflicts,
        depth=3,
    )

    assert result.dialectic_depth_executed == 3
    assert len(result.passes) == 3
    assert "Pass 0" in result.passes[0].pass_name
    assert "Pass 1" in result.passes[1].pass_name
    assert "Pass 2" in result.passes[2].pass_name
    assert result.kv_cache_preserved is True
    assert "辩证调和共识" in result.reconciled_directive


def test_clean_state_zero_conflicts_dialectic() -> None:
    """Verify clean state when no contradictions exist produces minimal overhead."""
    dialectic_engine = DialecticReconciliationEngine()
    history = ["采用 TypeScript strict 模式", "单文件严格小于400行"]
    current_prompt = "请添加一个新的图表组件，遵守400行规范"

    conflicts = dialectic_engine.detect_conflicts(history, current_prompt)
    assert len(conflicts) == 0

    result = dialectic_engine.reconcile(
        session_id="sess_102",
        turn_index=2,
        conflicts=conflicts,
        depth=2,
    )
    assert result.dialectic_depth_executed == 0
    assert result.token_cost_estimate < 20
    assert "DIALECTIC_CLEAN" in result.reconciled_directive


def test_end_to_end_orchestrator_turn_preparation() -> None:
    """Verify TwoLayerDialecticOrchestrator coordinates Layer 1 & 2 seamlessly."""
    config = DialecticCadenceConfig(
        context_cadence=3,
        dialectic_cadence=2,
        dialectic_depth=2,
        dialectic_reasoning_level=DialecticReasoningLevel.STANDARD,
    )
    orchestrator = TwoLayerDialecticOrchestrator(config=config)

    # Turn 2: Matches dialectic cadence (2 % 2 == 0)
    payload = orchestrator.prepare_turn(
        session_id="sess_200",
        turn_index=2,
        raw_user_message="我们现在要进行架构升级，打破以往做法",
        session_summary="已完成阶段1",
        peer_card_summary="DevBot",
        historical_assertions=["保持旧版兼容模式"],
    )

    assert payload.session_id == "sess_200"
    assert payload.turn_index == 2
    assert payload.kv_cache_preserved is True
    assert payload.base_context.generation_turn == 2
    assert payload.dialectic_result is not None
    assert payload.total_token_overhead > 0
    assert "BASE_CONTEXT_KV_CACHE_PROTECTED" in payload.augmented_user_message
    assert "DIALECTIC_RECONCILIATION_DIRECTIVE" in payload.augmented_user_message
