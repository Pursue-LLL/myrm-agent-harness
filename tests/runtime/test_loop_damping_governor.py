"""自适应循环计算预算与思考振荡阻尼治理单元测试.

覆盖输入信息熵自适应预算、单向单调升格、乒乓编辑横跳检测、人机决策卡生成与综合阻尼早停.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.loop_damping_governor import (
    AdaptiveBudgetScheduler,
    LoopDampingAction,
    LoopDampingGovernor,
    OscillationPatternType,
    TaskComplexityTier,
    ThoughtOscillationDetector,
)


def test_adaptive_budget_scheduler_inference_and_escalation() -> None:
    """验证输入推断、自适应阶梯预算与单向单调升格机制."""
    # 1. 极简点状任务推断
    simple_tier = AdaptiveBudgetScheduler.infer_tier_from_input(
        user_prompt="修复 README 里的一个拼写错误",
        context_files_count=1,
        estimated_code_lines=10,
    )
    assert simple_tier == TaskComplexityTier.POINT_TASK

    # 2. 深度重构与架构任务推断
    deep_tier = AdaptiveBudgetScheduler.infer_tier_from_input(
        user_prompt="全面重构运行时的事件总线与持久化架构",
        context_files_count=6,
        estimated_code_lines=600,
    )
    assert deep_tier == TaskComplexityTier.DEEP_REFACTOR

    # 3. 初始为标准任务（预算 8 轮）
    scheduler = AdaptiveBudgetScheduler(initial_tier=TaskComplexityTier.STANDARD_FEATURE)
    assert scheduler.max_loops == 8

    # 步骤 5 尚未耗尽
    dec1 = scheduler.evaluate_budget(current_loop=5)
    assert dec1.is_exhausted is False
    assert dec1.remaining_loops == 3

    # 步骤 8 耗尽
    dec2 = scheduler.evaluate_budget(current_loop=8)
    assert dec2.is_exhausted is True
    assert dec2.remaining_loops == 0

    # 4. 单向升格为深度架构任务（预算升至 20 轮）
    escalated = scheduler.escalate_tier(
        TaskComplexityTier.DEEP_REFACTOR,
        reason="发现深层依赖需要跨模块重构",
    )
    assert escalated is True
    assert scheduler.current_tier == TaskComplexityTier.DEEP_REFACTOR
    assert scheduler.max_loops == 20

    # 重新评估步骤 8，现在拥有 12 轮剩余
    dec3 = scheduler.evaluate_budget(current_loop=8)
    assert dec3.is_exhausted is False
    assert dec3.remaining_loops == 12

    # 5. 尝试降级应被拒绝，保证预算分配单调性
    downgraded = scheduler.escalate_tier(
        TaskComplexityTier.POINT_TASK,
        reason="尝试逆向降级",
    )
    assert downgraded is False
    assert scheduler.current_tier == TaskComplexityTier.DEEP_REFACTOR


def test_thought_oscillation_detector_ping_pong_detection() -> None:
    """验证乒乓编辑模式（A -> B -> A）精准捕获与人机裁定卡生成."""
    detector = ThoughtOscillationDetector(window_size=4)
    target = "src/cache/lru_cache.py"

    # Step 1: 写入方案 A
    detector.record_action(
        step_index=1,
        target_identifier=target,
        state_signature="hash_plan_a_sync_mutex",
        summary="方案 A: 采用标准线程锁互斥保护缓存",
    )
    assert detector.detect_oscillation().is_oscillating is False

    # Step 2: 写入方案 B
    detector.record_action(
        step_index=2,
        target_identifier=target,
        state_signature="hash_plan_b_lock_free_ring",
        summary="方案 B: 重构为无锁环形队列提高并发吞吐",
    )
    assert detector.detect_oscillation().is_oscillating is False

    # Step 3: 又撤销方案 B 改回方案 A（乒乓横跳）
    detector.record_action(
        step_index=3,
        target_identifier=target,
        state_signature="hash_plan_a_sync_mutex",
        summary="方案 A: 发现环形队列内存不确定，撤回方案并重新使用互斥锁",
    )

    verdict = detector.detect_oscillation()
    assert verdict.is_oscillating is True
    assert verdict.pattern == OscillationPatternType.PING_PONG_EDIT
    assert target in verdict.affected_targets
    assert verdict.tiebreaker_card is not None

    card = verdict.tiebreaker_card
    assert card.affected_target == target
    assert "采用标准线程锁" in card.option_a_summary
    assert "重构为无锁环形队列" in card.option_b_summary
    assert "方案 A" in card.recommended_option


def test_thought_oscillation_detector_cyclic_and_zero_progress() -> None:
    """验证工具链二元闭环循环与连续零增量空转检测."""
    # 1. 工具链循环闭环检测 (T1 -> T2 -> T1 -> T2)
    detector_cyclic = ThoughtOscillationDetector(window_size=4)
    detector_cyclic.record_action(1, "web_search", "query_apple")
    detector_cyclic.record_action(2, "read_file", "doc_apple")
    detector_cyclic.record_action(3, "web_search", "query_apple")
    detector_cyclic.record_action(4, "read_file", "doc_apple")

    v_cyclic = detector_cyclic.detect_oscillation()
    assert v_cyclic.is_oscillating is True
    assert v_cyclic.pattern == OscillationPatternType.CYCLIC_TOOL_CHAIN
    assert set(v_cyclic.affected_targets) == {"web_search", "read_file"}

    # 2. 连续 3 步完全无语义变化的空转检测
    detector_zero = ThoughtOscillationDetector(window_size=4)
    detector_zero.record_action(1, "build_script.sh", "error_code_127")
    detector_zero.record_action(2, "build_script.sh", "error_code_127")
    detector_zero.record_action(3, "build_script.sh", "error_code_127")

    v_zero = detector_zero.detect_oscillation()
    assert v_zero.is_oscillating is True
    assert v_zero.pattern == OscillationPatternType.ZERO_SEMANTIC_PROGRESS
    assert "build_script.sh" in v_zero.affected_targets


def test_loop_damping_governor_comprehensive_verdicts() -> None:
    """验证 LoopDampingGovernor 的综合判决流（健康继续、振荡阻断、饱和早停、预算耗尽）."""
    governor = LoopDampingGovernor(initial_tier=TaskComplexityTier.POINT_TASK)  # 预算 3 轮

    # Step 1: 正常单步探索 -> CONTINUE
    res1 = governor.evaluate_step(
        step_index=1,
        target_identifier="file_x.py",
        state_signature="v1",
        summary="initial change",
    )
    assert res1.action == LoopDampingAction.CONTINUE

    # Step 2: 意图达到饱和 -> EARLY_FINISH_SATURATED
    res2 = governor.evaluate_step(
        step_index=2,
        target_identifier="file_x.py",
        state_signature="v2",
        summary="second change",
        is_model_saturated=True,
    )
    assert res2.action == LoopDampingAction.EARLY_FINISH_SATURATED

    # Step 3: 达到预算上限 3 轮 -> BUDGET_EXHAUSTED
    res3 = governor.evaluate_step(
        step_index=3,
        target_identifier="file_x.py",
        state_signature="v3",
        summary="third change",
    )
    assert res3.action == LoopDampingAction.BUDGET_EXHAUSTED

    # 验证振荡优先于预算耗尽被拦截
    governor_osc = LoopDampingGovernor(initial_tier=TaskComplexityTier.STANDARD_FEATURE)
    governor_osc.evaluate_step(1, "file_y.py", "sig_a", "step 1")
    governor_osc.evaluate_step(2, "file_y.py", "sig_b", "step 2")
    res_osc = governor_osc.evaluate_step(3, "file_y.py", "sig_a", "step 3 revert")
    assert res_osc.action == LoopDampingAction.DAMPED_HALT_OSCILLATION
    assert res_osc.oscillation is not None
    assert res_osc.oscillation.is_oscillating is True


def test_healthy_non_oscillating_progression() -> None:
    """验证正常的持续迭代更新（v1 -> v2 -> v3 -> v4）绝不发生误报."""
    detector = ThoughtOscillationDetector(window_size=4)
    target = "main.py"

    detector.record_action(1, target, "sig_commit_1")
    detector.record_action(2, target, "sig_commit_2")
    detector.record_action(3, target, "sig_commit_3")
    detector.record_action(4, target, "sig_commit_4")

    verdict = detector.detect_oscillation()
    assert verdict.is_oscillating is False
