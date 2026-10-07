"""单元测试：权限撤销触发的短期记忆与上下文数据选择性擦除/净化套件 (Item 206).

[INPUT]
- RevocationEvictionEngine
- RevocationDirective
- RevocationScopeKind
- SanitizationOutcome
- TaintedContentBlock

[OUTPUT]
- 验证针对敏感轮次的靶向上下文物理擦除与占位替换
- 验证短期工作记忆中关联条目的物理驱逐
- 验证多权限作用域隔离互不影响
- 验证审计链路日志与指标序列化契约
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.revocation_eviction import (
    RevocationDirective,
    RevocationEvictionEngine,
    RevocationScopeKind,
    SanitizationOutcome,
    TaintedContentBlock,
)


def test_surgical_context_sanitization() -> None:
    """验证靶向净化：权限撤销时精准抹除敏感轮次内容，非敏感上下文完全保留。"""
    engine = RevocationEvictionEngine()

    messages: list[dict[str, object]] = [
        {"role": "user", "content": "请分析市场公开报告"},
        {"role": "assistant", "content": "公开报告表明市场增长稳健。"},
        {"role": "user", "content": "查询薪资机密库"},
        {
            "role": "assistant",
            "content": "薪资机密数据：CEO 年薪 500 万，CTO 年薪 400 万。",
            "tool_calls": [{"name": "read_payroll", "args": {"db": "payroll_v1"}}],
        },
    ]

    # 注册 Turn 3 包含机密薪资库数据
    engine.register_tainted_block(
        block_id="block_salary_01",
        turn_index=3,
        scope_kind=RevocationScopeKind.RESOURCE_ID,
        scope_id="scope_payroll",
        resource_name="PayrollDatabase",
        char_count=120,
    )

    directive = RevocationDirective(
        revocation_id="rev_001",
        scope_id="scope_payroll",
        reason="安全审计下线薪资访问授权",
        evict_working_memory=True,
    )

    outcome, _ = engine.execute_surgical_revocation(messages, directive)

    assert outcome.sanitized_turns_count == 1
    assert outcome.purged_blocks_count == 1
    assert outcome.scope_id == "scope_payroll"

    # Turn 0 和 Turn 1 保持不变
    assert outcome.cleansed_messages[0]["content"] == "请分析市场公开报告"
    assert outcome.cleansed_messages[1]["content"] == "公开报告表明市场增长稳健。"

    # Turn 3 被物理脱敏净化，机密数字彻底消失
    cleansed_turn_3 = outcome.cleansed_messages[3]
    content_str = str(cleansed_turn_3["content"])
    assert "CEO 年薪" not in content_str
    assert "500 万" not in content_str
    assert "[Data Expunged:" in content_str
    assert "PayrollDatabase" in content_str
    assert cleansed_turn_3["tool_calls"] == []


def test_working_memory_eviction() -> None:
    """验证短期记忆驱逐：带有被撤销 scope 或敏感资源标签的记忆条目被物理驱逐。"""
    engine = RevocationEvictionEngine()

    engine.register_tainted_block(
        block_id="b1",
        turn_index=1,
        scope_kind=RevocationScopeKind.RESOURCE_ID,
        scope_id="scope_token_vault",
        resource_name="StripeVault",
        char_count=50,
    )

    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "secret token data"},
    ]

    working_memory: list[dict[str, object]] = [
        {"scope_id": "scope_public", "fact": "用户常用 Python 语言"},
        {"scope_id": "scope_token_vault", "fact": "StripeVault API Key: sk_live_xxx"},
        {"scope_id": "scope_public", "fact": "用户处于北京时区"},
    ]

    directive = RevocationDirective(
        revocation_id="rev_002",
        scope_id="scope_token_vault",
        reason="密钥权限失效",
        evict_working_memory=True,
    )

    outcome, cleansed_memory = engine.execute_surgical_revocation(
        messages, directive, working_memory
    )

    assert outcome.evicted_memory_entries_count == 1
    assert len(cleansed_memory) == 2
    for entry in cleansed_memory:
        assert entry["scope_id"] != "scope_token_vault"
        assert "sk_live_xxx" not in str(entry.get("fact", ""))


def test_multiple_scope_isolation() -> None:
    """验证多权限域隔离：撤销 Scope A 时，仅净化 Scope A，Scope B 保持完好。"""
    engine = RevocationEvictionEngine()

    messages = [
        {"role": "assistant", "content": "Scope A 机密数据"},
        {"role": "assistant", "content": "Scope B 研发专利数据"},
    ]

    engine.register_tainted_block("b_a", 0, RevocationScopeKind.TAG, "scope_a", "ResourceA", 40)
    engine.register_tainted_block("b_b", 1, RevocationScopeKind.TAG, "scope_b", "ResourceB", 40)

    directive_a = RevocationDirective(revocation_id="rev_a", scope_id="scope_a")
    outcome, _ = engine.execute_surgical_revocation(messages, directive_a)

    assert outcome.sanitized_turns_count == 1
    # Turn 0 被净化
    assert "[Data Expunged:" in str(outcome.cleansed_messages[0]["content"])
    # Turn 1 保持完好
    assert outcome.cleansed_messages[1]["content"] == "Scope B 研发专利数据"


def test_audit_trail_and_metrics_contract() -> None:
    """验证审计日志记录、执行耗时与 JSON 字典序列化契约。"""
    engine = RevocationEvictionEngine()

    engine.register_tainted_block("b_x", 0, RevocationScopeKind.DATASOURCE, "db_fin", "FinDB", 80)
    messages = [{"role": "assistant", "content": "敏感财务数字"}]

    directive = RevocationDirective(revocation_id="rev_audit_test", scope_id="db_fin")
    outcome, _ = engine.execute_surgical_revocation(messages, directive)

    assert outcome.duration_ms >= 0.0
    assert len(outcome.audit_trail) >= 2
    assert "Revocation initiated" in outcome.audit_trail[0]

    as_dict = outcome.to_dict()
    assert as_dict["revocation_id"] == "rev_audit_test"
    assert as_dict["scope_id"] == "db_fin"
    assert as_dict["sanitized_turns_count"] == 1
    assert isinstance(as_dict["audit_trail"], list)
