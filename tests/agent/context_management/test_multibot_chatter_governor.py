"""Unit tests for MultiBotSharedGroupInfinitePingPongChatterGovernor.

Validates continuous bot turn watchdog circuit-breaker, incremental cognitive value
gate introspection, turn mutex arbitration, and emergency braking.
"""

from __future__ import annotations

import time

from myrm_agent_harness.agent.context_management.multibot_governor import (
    BotTurnEvent,
    GovernorAction,
    GroupTurnArbitrator,
    IncrementalCognitiveValueEvaluator,
    MessageSenderRole,
    MultiBotChatterGovernor,
    MultiBotGovernorConfig,
)


def test_continuous_bot_turns_circuit_breaker_and_user_reset() -> None:
    """Verifies that continuous bot-to-bot replies trip circuit breaker at threshold and reset on human input."""
    config = MultiBotGovernorConfig(max_continuous_bot_turns=2)
    governor = MultiBotChatterGovernor(config=config)
    group_id = "group-dev-chat-101"

    # Turn 0: User inputs initial topic
    user_event = BotTurnEvent(
        sender_id="user_alice",
        sender_role=MessageSenderRole.USER,
        content="请讨论一下这套架构方案的优缺点",
    )
    governor.record_event(group_id, user_event)
    assert governor.get_continuous_bot_turns(group_id) == 0

    # Bot 1 speaks (Turn 1)
    bot1_event = BotTurnEvent(
        sender_id="bot_deepseek",
        sender_role=MessageSenderRole.BOT,
        content="该方案采用异步事件流设计，具有高吞吐特性，但需要关注背压控制。",
    )
    decision1 = governor.evaluate_turn(group_id, "bot_deepseek", user_event)
    assert decision1.action == GovernorAction.ALLOW
    assert decision1.should_respond is True
    assert decision1.mutex_token_id is not None
    governor.record_event(group_id, bot1_event)
    assert governor.get_continuous_bot_turns(group_id) == 1
    # Bot 1 finishes turn and releases mutex
    governor.release_turn(group_id, "bot_deepseek", decision1.mutex_token_id)

    # Bot 2 speaks in response (Turn 2)
    bot2_event = BotTurnEvent(
        sender_id="bot_yuanbao",
        sender_role=MessageSenderRole.BOT,
        content="针对背压控制，我们可以引入定长环形缓冲区和滑动窗口自适应降级。",
    )
    decision2 = governor.evaluate_turn(group_id, "bot_yuanbao", bot1_event)
    assert decision2.action == GovernorAction.ALLOW
    assert decision2.mutex_token_id is not None
    governor.record_event(group_id, bot2_event)
    assert governor.get_continuous_bot_turns(group_id) == 2
    # Bot 2 finishes turn and releases mutex
    governor.release_turn(group_id, "bot_yuanbao", decision2.mutex_token_id)

    # Bot 1 tries to speak again (Turn 3) -> Exceeds max_continuous_bot_turns (2)
    decision3 = governor.evaluate_turn(group_id, "bot_deepseek", bot2_event)
    assert decision3.action == GovernorAction.CIRCUIT_BREAK
    assert decision3.should_respond is False
    assert decision3.notice_message is not None
    assert "已完成 2 轮 AI 自主协作接力" in decision3.notice_message

    # Human user intervenes with feedback
    human_intervene = BotTurnEvent(
        sender_id="user_alice",
        sender_role=MessageSenderRole.USER,
        content="很好，定长缓冲区方案可行，请继续细化实现细节。",
    )
    governor.record_event(group_id, human_intervene)
    assert governor.get_continuous_bot_turns(group_id) == 0

    # Bot can speak again after human reset
    decision_after_reset = governor.evaluate_turn(group_id, "bot_deepseek", human_intervene)
    assert decision_after_reset.action == GovernorAction.ALLOW
    assert decision_after_reset.should_respond is True


def test_incremental_cognitive_value_evaluator_platitude_suppression() -> None:
    """Verifies that polite platitudes and unaddressed chatter are suppressed via PASS."""
    evaluator = IncrementalCognitiveValueEvaluator()

    # Self-talk suppression
    self_event = BotTurnEvent(
        sender_id="bot_a",
        sender_role=MessageSenderRole.BOT,
        content="这是我自己发出的内容",
    )
    res_self = evaluator.evaluate("bot_a", self_event)
    assert res_self.action == GovernorAction.PASS
    assert res_self.should_respond is False

    # Polite platitudes suppression
    platitude_event = BotTurnEvent(
        sender_id="bot_b",
        sender_role=MessageSenderRole.BOT,
        content="完全赞同你的观点，说的很对！",
    )
    res_platitude = evaluator.evaluate("bot_a", platitude_event)
    assert res_platitude.action == GovernorAction.PASS
    assert res_platitude.should_respond is False
    assert "platitude" in res_platitude.reason

    # Open rhetorical echo suppression
    rhetorical_event = BotTurnEvent(
        sender_id="bot_b",
        sender_role=MessageSenderRole.BOT,
        content="你觉得呢？",
    )
    res_rhetorical = evaluator.evaluate("bot_a", rhetorical_event)
    assert res_rhetorical.action == GovernorAction.PASS

    # Explicit mention overrides and permits response
    mention_event = BotTurnEvent(
        sender_id="bot_b",
        sender_role=MessageSenderRole.BOT,
        content="关于存储选型，请 @bot_a 给出具体压测基准数据",
        mentioned_bot_ids=("bot_a",),
    )
    res_mention = evaluator.evaluate("bot_a", mention_event)
    assert res_mention.action == GovernorAction.ALLOW
    assert res_mention.should_respond is True
    assert res_mention.is_explicitly_mentioned is True


def test_group_turn_arbitrator_mutex_token() -> None:
    """Verifies exclusive mutex locking prevents collision-answering across bots."""
    arbitrator = GroupTurnArbitrator()
    group_id = "group-collab-202"

    # Bot A acquires mutex
    res_a = arbitrator.acquire(group_id, "bot_a", lease_seconds=10.0)
    assert res_a.acquired is True
    assert res_a.token_id is not None
    token_a = res_a.token_id

    # Bot B attempts to acquire while Bot A holds lease -> Rejected
    res_b = arbitrator.acquire(group_id, "bot_b", lease_seconds=10.0)
    assert res_b.acquired is False
    assert res_b.holder_bot_id == "bot_a"

    # Bot A re-acquires (lease extension) -> Allowed
    res_reenter = arbitrator.acquire(group_id, "bot_a", lease_seconds=15.0)
    assert res_reenter.acquired is True
    assert res_reenter.token_id == token_a

    # Bot A releases mutex
    released = arbitrator.release(group_id, "bot_a", token_a)
    assert released is True

    # Bot B can now acquire mutex
    res_b_after = arbitrator.acquire(group_id, "bot_b", lease_seconds=10.0)
    assert res_b_after.acquired is True
    assert res_b_after.holder_bot_id == "bot_b"


def test_emergency_stop_trip_and_reset() -> None:
    """Verifies that emergency stop halts all bot activity instantly."""
    governor = MultiBotChatterGovernor()
    group_id = "group-ops-303"

    user_event = BotTurnEvent(
        sender_id="user_bob",
        sender_role=MessageSenderRole.USER,
        content="开始自动化部署",
    )

    decision_normal = governor.evaluate_turn(group_id, "bot_agent", user_event)
    assert decision_normal.action == GovernorAction.ALLOW

    # User clicks emergency stop
    governor.trigger_emergency_stop(group_id)

    decision_stopped = governor.evaluate_turn(group_id, "bot_agent", user_event)
    assert decision_stopped.action == GovernorAction.EMERGENCY_STOP
    assert decision_stopped.should_respond is False
    assert decision_stopped.notice_message is not None

    # Reset emergency stop
    governor.reset_emergency_stop(group_id)
    decision_resumed = governor.evaluate_turn(group_id, "bot_agent", user_event)
    assert decision_resumed.action == GovernorAction.ALLOW
