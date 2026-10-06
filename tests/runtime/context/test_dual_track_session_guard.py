"""Tests for Dual-Track Session Scenario Context Isolator and Token Burn Guard."""

from __future__ import annotations

from myrm_agent_harness.runtime.context.dual_track_session_guard import (
    BurnGuardAction,
    DualTrackSessionGuardHub,
    IntentCategory,
    SessionScenarioTrack,
    TokenBurnGuard,
    UserIntentClassifier,
)


def test_user_intent_classifier():
    # 1. Engineering Dev intent
    assert UserIntentClassifier.classify_intent("Please fix the bug in server.py") == IntentCategory.ENGINEERING_DEV
    assert UserIntentClassifier.classify_intent("Inspect @file:src/app.ts") == IntentCategory.ENGINEERING_DEV
    assert UserIntentClassifier.classify_intent("```python\nprint(1)\n```") == IntentCategory.ENGINEERING_DEV
    assert UserIntentClassifier.classify_intent("给这段代码补充单测并做重构") == IntentCategory.ENGINEERING_DEV

    # 2. General QA / Chat intent
    assert UserIntentClassifier.classify_intent("你好！") == IntentCategory.GENERAL_QA_OR_CHAT
    assert UserIntentClassifier.classify_intent("帮我写个周报总结，本周完成了需求评审") == IntentCategory.GENERAL_QA_OR_CHAT
    assert UserIntentClassifier.classify_intent("推荐几部经典的科幻电影") == IntentCategory.GENERAL_QA_OR_CHAT
    assert UserIntentClassifier.classify_intent("") == IntentCategory.GENERAL_QA_OR_CHAT


def test_thinking_qa_track_strictly_strips_workspace():
    decision = TokenBurnGuard.evaluate_guard(
        track=SessionScenarioTrack.THINKING_QA_TRACK,
        prompt="Explain quantum entanglement in simple terms",
        workspace_tokens=30000,
        base_prompt_tokens=1500,
    )

    assert decision.action == BurnGuardAction.PASSTHROUGH
    assert decision.workspace_stripped is True
    assert decision.estimated_tokens_saved == 30000
    assert decision.savings_percentage > 0.90
    assert decision.user_advisory_message is None


def test_dev_track_code_prompt_includes_workspace():
    decision = TokenBurnGuard.evaluate_guard(
        track=SessionScenarioTrack.DEV_TRACK,
        prompt="Refactor the authentication handler in auth.py",
        workspace_tokens=30000,
        base_prompt_tokens=1500,
    )

    assert decision.action == BurnGuardAction.PASSTHROUGH
    assert decision.detected_intent == IntentCategory.ENGINEERING_DEV
    assert decision.workspace_stripped is False
    assert decision.estimated_tokens_saved == 0
    assert decision.savings_percentage == 0.0
    assert decision.user_advisory_message is None


def test_dev_track_general_chat_triggers_throttle_burn_guard():
    decision = TokenBurnGuard.evaluate_guard(
        track=SessionScenarioTrack.DEV_TRACK,
        prompt="你好，请问你是谁？",
        workspace_tokens=25000,
        base_prompt_tokens=1500,
    )

    assert decision.action == BurnGuardAction.THROTTLE_WORKSPACE_CONTEXT
    assert decision.detected_intent == IntentCategory.GENERAL_QA_OR_CHAT
    assert decision.workspace_stripped is True
    assert decision.estimated_tokens_saved == 25000
    assert decision.savings_percentage > 0.90
    assert decision.user_advisory_message is not None
    assert "25,000 Token" in decision.user_advisory_message
    assert "已自动为您节流工作区工程上下文" in decision.user_advisory_message


def test_dual_track_session_guard_hub_assemble_context():
    base_prompt = "You are Myrm Assistant."
    workspace_ctx = "<workspace_tree>1000 files</workspace_tree>"

    # 1. Dev track with code prompt -> includes workspace
    assembly_dev = DualTrackSessionGuardHub.assemble_context(
        track=SessionScenarioTrack.DEV_TRACK,
        prompt="Fix syntax error in main.py",
        base_system_prompt=base_prompt,
        workspace_context=workspace_ctx,
        estimated_workspace_tokens=20000,
    )
    assert assembly_dev.workspace_included is True
    assert "<workspace_tree>1000 files</workspace_tree>" in assembly_dev.assembled_system_prompt
    assert assembly_dev.decision.action == BurnGuardAction.PASSTHROUGH

    # 2. Dev track with greeting prompt -> throttles workspace
    assembly_chat = DualTrackSessionGuardHub.assemble_context(
        track=SessionScenarioTrack.DEV_TRACK,
        prompt="你好",
        base_system_prompt=base_prompt,
        workspace_context=workspace_ctx,
        estimated_workspace_tokens=20000,
    )
    assert assembly_chat.workspace_included is False
    assert "<workspace_tree>" not in assembly_chat.assembled_system_prompt
    assert assembly_chat.assembled_system_prompt == base_prompt
    assert assembly_chat.decision.action == BurnGuardAction.THROTTLE_WORKSPACE_CONTEXT

    # 3. Dev track with auto_throttle disabled -> retains workspace even on greeting
    assembly_override = DualTrackSessionGuardHub.assemble_context(
        track=SessionScenarioTrack.DEV_TRACK,
        prompt="你好",
        base_system_prompt=base_prompt,
        workspace_context=workspace_ctx,
        estimated_workspace_tokens=20000,
        auto_throttle=False,
    )
    assert assembly_override.workspace_included is True
    assert "<workspace_tree>" in assembly_override.assembled_system_prompt
