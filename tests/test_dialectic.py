# [POS] myrm-agent-harness/tests/test_dialectic.py
# [INPUT] DialecticCadenceConfig, DialecticCadenceGovernor, DialecticReasoningEngine, SessionHeatState from dialectic
# [OUTPUT] 辩证推理深度用户表征与自适应会话步调动态节流完整单元测试

"""辩证推理深度用户表征与自适应会话步调动态节流单元测试。"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.dialectic import (
    DialecticCadenceConfig,
    DialecticCadenceGovernor,
    DialecticReasoningEngine,
    SessionHeatState,
)


def test_dialectic_cadence_governor_heat_and_throttling() -> None:
    """测试会话步调控制器的冷热状态变迁与步调节流判定。"""
    config = DialecticCadenceConfig(
        base_profile_cadence_turns=4,
        ephemeral_cadence_turns=2,
        cold_boot_threshold_turns=2,
    )
    governor = DialecticCadenceGovernor(config=config)
    conv_id = "test-session-01"

    # Turn 1: 冷启动首轮，应当触发提炼
    governor.record_turn(conv_id)
    assert governor.get_heat_state(conv_id) == SessionHeatState.COLD_BOOT
    assert governor.should_extract_ephemeral(conv_id) is True
    governor.mark_ephemeral_extracted(conv_id)

    # Turn 2: 冷启动第二轮，未到 2 轮间隔，应当被节流
    governor.record_turn(conv_id)
    assert governor.get_heat_state(conv_id) == SessionHeatState.COLD_BOOT
    assert governor.should_extract_ephemeral(conv_id) is False

    # Turn 3: 达到 2 轮间隔，应当再次触发提炼，且状态进入 WARM
    governor.record_turn(conv_id)
    assert governor.get_heat_state(conv_id) == SessionHeatState.WARM
    assert governor.should_extract_ephemeral(conv_id) is True
    governor.mark_ephemeral_extracted(conv_id)

    # Turn 5: 轮次超过 4 轮，状态进入 HOT_ACTIVE
    governor.record_turn(conv_id, turn_index=5)
    assert governor.get_heat_state(conv_id) == SessionHeatState.HOT_ACTIVE


def test_dialectic_reasoning_engine_extraction_and_slice() -> None:
    """测试辩证推理引擎深层提取抗拒点、隐式目标与生成前缀缓存友好切片。"""
    config = DialecticCadenceConfig(
        ephemeral_cadence_turns=2,
        max_ephemeral_chars=300,
    )
    engine = DialecticReasoningEngine(config=config)
    conv_id = "dialectic-conv-02"

    # Turn 1 提炼
    prompt = "我们要重构记忆系统。核心目标是保证极致的单机运行性能，严禁引入外部 Redis 依赖，并且避免复杂的向后兼容。"
    res = engine.process_turn(conv_id, prompt)

    assert res.is_throttled is False
    assert res.ephemeral_mind_updated is True
    assert res.ephemeral_mind is not None
    assert "单机运行性能" in " ".join(res.ephemeral_mind.implicit_goals)
    assert any("Redis" in r for r in res.ephemeral_mind.resistance_points)

    # 验证切片包含格式化标头且字数紧凑
    assert "<!-- [USER DIALECTIC MIND]" in res.prompt_volatile_slice
    assert len(res.prompt_volatile_slice) <= 300

    # Turn 2 应当被步调节流直接阻断，复用上一轮切片，零额外开销
    res_throttled = engine.process_turn(conv_id, "请帮我写出具体的类定义")
    assert res_throttled.is_throttled is True
    assert res_throttled.ephemeral_mind_updated is False
    assert "throttled by cadence governor" in res_throttled.reasoning_summary
    assert res_throttled.prompt_volatile_slice == res.prompt_volatile_slice


def test_dialectic_reasoning_engine_cold_boot_tag() -> None:
    """测试冷启动阶段的焦点打上探测标记。"""
    config = DialecticCadenceConfig(cold_boot_threshold_turns=2)
    engine = DialecticReasoningEngine(config=config)

    res = engine.process_turn("conv-cold", "你好，我是系统的核心架构师，准备做一次全栈模块拆分。")
    assert res.heat_state == SessionHeatState.COLD_BOOT
    assert res.ephemeral_mind is not None
    assert "[冷启动画像探测]" in res.ephemeral_mind.immediate_focus
