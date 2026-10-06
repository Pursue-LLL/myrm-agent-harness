"""Unit tests for session state soft-reset and instant memory consolidation engine."""

from __future__ import annotations

import concurrent.futures

from myrm_agent_harness.runtime.context.session_soft_reset import (
    InstantMemoryVault,
    ResetIntentDetector,
    SessionSoftResetEngine,
)
from myrm_agent_harness.runtime.context.session_soft_reset_types import (
    ResetTriggerKind,
)


def test_reset_intent_detector() -> None:
    """Verifies recognition of slash commands and natural language reset intents."""
    slash_inputs = ["/reset", " /clear ", "/restart"]
    for s in slash_inputs:
        is_reset, trigger = ResetIntentDetector.detect_reset_intent(s)
        assert is_reset is True
        assert trigger == ResetTriggerKind.EXPLICIT_SLASH_COMMAND

    natural_inputs = [
        "咱们把刚才聊乱的翻篇吧，重新开始聊新功能",
        "太乱了，请清空当前对话",
        "let us start over from scratch",
        "重置当前会话，重新梳理架构",
    ]
    for n in natural_inputs:
        is_reset, trigger = ResetIntentDetector.detect_reset_intent(n)
        assert is_reset is True
        assert trigger == ResetTriggerKind.NATURAL_LANGUAGE_INTENT

    benign_inputs = [
        "How do I clear a python list efficiently?",
        "Please restart the docker container using bash",
        "我们继续写代码吧",
    ]
    for b in benign_inputs:
        is_reset, trigger = ResetIntentDetector.detect_reset_intent(b)
        assert is_reset is False
        assert trigger is None


def test_instant_memory_vault_extraction() -> None:
    """Verifies that user preferences, facts, and lessons are distilled prior to wiping window."""
    history = [
        {"role": "user", "content": "我的技术栈偏好是 Python 3.13 搭配 FastAPI，喜欢使用 Pydantic V2。"},
        {"role": "assistant", "content": "了解。系统服务配置端口为 8000，config path: /etc/myrm/config.yaml。"},
        {"role": "user", "content": "刚才调试踩坑了，排查发现旧依赖版本存在并发死锁问题。"},
        {"role": "assistant", "content": "已记录该教训并升级依赖版本。"},
    ]

    vaulted = InstantMemoryVault.consolidate_and_vault("sess-demo", history, current_time=1000.0)
    assert vaulted.session_id == "sess-demo"
    assert vaulted.pre_reset_message_count == 4
    assert len(vaulted.items) >= 3

    categories = {it.category for it in vaulted.items}
    assert "preference" in categories
    assert "fact" in categories
    assert "lesson" in categories
    assert "sess-demo" in vaulted.summary_digest


def test_session_soft_reset_execution_and_baseline_reload() -> None:
    """Verifies execution of soft-reset: wiping messages while reloading baseline with learnings."""
    engine = SessionSoftResetEngine()
    session_id = "sess-active-42"
    base_prompt = "You are Myrm Architect Agent. Follow PEP8."

    history = [
        {"role": "user", "content": "偏好代码无 Any 类型，严格小于 400 行。"},
        {"role": "assistant", "content": "收到，严格遵循代码规范。"},
    ]

    result = engine.execute_soft_reset(
        session_id=session_id,
        messages=history,
        trigger=ResetTriggerKind.EXPLICIT_SLASH_COMMAND,
        baseline_system_prompt=base_prompt,
        current_time=2000.0,
    )

    assert result.session_id == session_id
    assert result.trigger_kind == ResetTriggerKind.EXPLICIT_SLASH_COMMAND
    assert result.cleared_message_count == 2
    assert "<vaulted_learnings" in result.system_baseline_prompt
    assert "无 Any 类型" in result.system_baseline_prompt
    assert "会话已干净翻篇" in result.acknowledgment_message
    assert result.reloaded_baseline_tokens > 0

    # Vault audit retrieval
    audit = engine.get_session_vaulted_memories(session_id)
    assert len(audit) == 1
    assert audit[0].pre_reset_message_count == 2


def test_soft_reset_with_empty_history() -> None:
    """Verifies that soft-reset on empty message history succeeds cleanly."""
    engine = SessionSoftResetEngine()
    base_prompt = "Base system prompt."

    result = engine.execute_soft_reset(
        session_id="sess-empty",
        messages=[],
        trigger=ResetTriggerKind.UI_ACTION_BUTTON,
        baseline_system_prompt=base_prompt,
    )
    assert result.cleared_message_count == 0
    assert len(result.vaulted_memory.items) == 0
    assert result.system_baseline_prompt == base_prompt
    assert "清空了 0 条历史" in result.acknowledgment_message


def test_thread_safe_concurrent_soft_resets() -> None:
    """Verifies thread-safety during concurrent soft resets across distinct sessions."""
    engine = SessionSoftResetEngine()

    def worker(i: int) -> None:
        sid = f"sess-thread-{i}"
        history = [{"role": "user", "content": f"用户偏好 #{i}: 选项 {i}"}]
        res = engine.execute_soft_reset(
            session_id=sid,
            messages=history,
            trigger=ResetTriggerKind.NATURAL_LANGUAGE_INTENT,
            baseline_system_prompt="Base prompt",
            current_time=float(i),
        )
        assert res.cleared_message_count == 1
        assert len(engine.get_session_vaulted_memories(sid)) == 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(30)]
        for f in concurrent.futures.as_completed(futures):
            f.result()
