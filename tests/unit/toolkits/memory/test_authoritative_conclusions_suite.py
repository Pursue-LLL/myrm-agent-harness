# [POS]: tests/unit/toolkits/memory/test_authoritative_conclusions_suite.py
# [INPUT]: myrm_agent_harness.toolkits.memory.authoritative_conclusions
# [OUTPUT]: Unit tests for Explicit Authoritative Conclusions and Audit Tooling Suite (Item 111)

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.authoritative_conclusions import (
    AuthoritativeConclusionStore,
    AuthoritativeConclusionToolSuite,
    ConclusionContextAnchor,
    ConclusionStatus,
    ConclusionToolAction,
    memory_conclude_tool,
)


def test_write_and_list_conclusions_with_audit() -> None:
    """Validate declaring authoritative conclusions, querying, and audit recording."""
    store = AuthoritativeConclusionStore()

    # 1. Write confirmed architectural conclusion
    conc1 = store.write_conclusion(
        content="本项目严禁使用 Any 类型，必须使用具体 Type Hints",
        peer_id="user_alice",
        scope_tag="code_style",
        operator_peer_id="user_alice",
        auto_confirm=True,
        rationale="Enforce strict typing across repo",
    )
    assert conc1.status == ConclusionStatus.CONFIRMED
    assert conc1.confirmed_at is not None
    assert conc1.scope_tag == "code_style"

    # 2. Write proposed security conclusion
    conc2 = store.write_conclusion(
        content="所有外部通信端点必须经过双向 mTLS 证书校验",
        peer_id="reviewer_bob",
        scope_tag="security",
        operator_peer_id="reviewer_bob",
        auto_confirm=False,
        rationale="Initial security recommendation",
    )
    assert conc2.status == ConclusionStatus.PROPOSED
    assert conc2.confirmed_at is None

    # 3. Query all
    all_concs = store.list_conclusions()
    assert len(all_concs) == 2

    # 4. Filter by status
    confirmed_only = store.list_conclusions(status=ConclusionStatus.CONFIRMED)
    assert len(confirmed_only) == 1
    assert confirmed_only[0].conclusion_id == conc1.conclusion_id

    # 5. Filter by scope and keyword
    style_concs = store.list_conclusions(scope_tag="code_style", keyword="Type Hints")
    assert len(style_concs) == 1
    assert "Type Hints" in style_concs[0].content

    # 6. Verify audit logs
    audits = store.list_audits(conc1.conclusion_id)
    assert len(audits) == 1
    assert audits[0].action == ConclusionToolAction.WRITE
    assert audits[0].new_status == ConclusionStatus.CONFIRMED


def test_deprecation_and_physical_deletion_lifecycle() -> None:
    """Validate deprecation state transition and PII physical deletion compliance."""
    store = AuthoritativeConclusionStore()

    conc = store.write_conclusion(
        content="临时测试结论: 使用 SQLite 内存库作为单测后端",
        peer_id="agent_architect",
        scope_tag="testing",
        operator_peer_id="agent_architect",
    )
    cid = conc.conclusion_id

    # 1. Deprecate conclusion
    deprecated = store.deprecate_conclusion(
        conclusion_id=cid,
        operator_peer_id="user_alice",
        rationale="Switched to persistent isolated SQLite per test",
    )
    assert deprecated is not None
    assert deprecated.status == ConclusionStatus.DEPRECATED
    assert deprecated.deprecated_at is not None

    # Verify deprecation audit record
    audits_after_dep = store.list_audits(cid)
    assert len(audits_after_dep) == 2
    assert audits_after_dep[1].action == ConclusionToolAction.DEPRECATE
    assert audits_after_dep[1].previous_status == ConclusionStatus.CONFIRMED
    assert audits_after_dep[1].new_status == ConclusionStatus.DEPRECATED

    # 2. Physically delete conclusion (e.g. for PII removal)
    deleted = store.delete_conclusion(
        conclusion_id=cid,
        operator_peer_id="security_admin",
        rationale="Confidential test parameter purge",
    )
    assert deleted is True
    assert store.get_conclusion(cid) is None

    # Verify deletion audit record was preserved
    audits_after_del = store.list_audits(cid)
    assert len(audits_after_del) == 3
    assert audits_after_del[2].action == ConclusionToolAction.DELETE
    assert audits_after_del[2].previous_status == ConclusionStatus.DEPRECATED
    assert audits_after_del[2].new_status is None


def test_anti_dilution_context_anchor() -> None:
    """Validate rendering high-salience prompt anchor block from confirmed conclusions."""
    store = AuthoritativeConclusionStore()
    anchor = ConclusionContextAnchor()

    # 1. Empty state
    empty_res = anchor.format_anchor_block([])
    assert empty_res.total_active_conclusions == 0
    assert empty_res.formatted_prompt_block == ""
    assert empty_res.token_estimate == 0

    # 2. Add confirmed and deprecated conclusions
    store.write_conclusion(
        content="严格遵守分层架构，Server 仓禁止 deep import Harness 内部子模块",
        peer_id="user_architect",
        scope_tag="architecture",
    )
    store.write_conclusion(
        content="所有凭证禁止写入日志，生产环境强制密钥脱敏",
        peer_id="reviewer_sec",
        scope_tag="security",
    )
    conc_dep = store.write_conclusion(
        content="已过时的设计规约",
        peer_id="user_old",
        scope_tag="legacy",
    )
    store.deprecate_conclusion(conc_dep.conclusion_id, operator_peer_id="user_architect")

    # 3. Format anchor block
    projection = anchor.format_anchor_block(store.list_conclusions())
    assert projection.total_active_conclusions == 2
    assert projection.token_estimate > 0
    block = projection.formatted_prompt_block
    assert "[AUTHORITATIVE ARCHITECTURAL & BUSINESS CONCLUSIONS]" in block
    assert "Scope [ARCHITECTURE]:" in block
    assert "严格遵守分层架构" in block
    assert "Scope [SECURITY]:" in block
    assert "所有凭证禁止写入日志" in block
    # Deprecated conclusion must be excluded
    assert "已过时的设计规约" not in block


def test_memory_conclude_meta_tool_execution() -> None:
    """Validate agent callable tool suite executing write, list, deprecate, delete."""
    suite = AuthoritativeConclusionToolSuite()

    # 1. Tool action: write
    write_resp = memory_conclude_tool(
        action="write",
        content="前端单文件严格不超过 400 行代码",
        peer_id="user_alice",
        scope_tag="code_style",
        rationale="Maintainability milestone",
        suite=suite,
    )
    assert "Successfully declared authoritative conclusion" in write_resp
    assert "code_style" in write_resp

    # 2. Tool action: list
    list_resp = memory_conclude_tool(
        action="list",
        suite=suite,
    )
    assert "Found 1 authoritative conclusions:" in list_resp
    assert "前端单文件严格不超过 400 行代码" in list_resp

    # Extract conclusion ID from list output
    cid = suite.store.list_conclusions()[0].conclusion_id

    # 3. Tool action: deprecate
    dep_resp = memory_conclude_tool(
        action="deprecate",
        conclusion_id=cid,
        peer_id="user_alice",
        rationale="Requirement adjusted",
        suite=suite,
    )
    assert f"Successfully deprecated conclusion [{cid}]" in dep_resp

    # 4. Tool action: delete
    del_resp = memory_conclude_tool(
        action="delete",
        conclusion_id=cid,
        peer_id="security_officer",
        rationale="GDPR purge",
        suite=suite,
    )
    assert f"Successfully erased conclusion [{cid}]" in del_resp

    # 5. Invalid action safeguard
    err_resp = memory_conclude_tool(
        action="invalid_action",
        suite=suite,
    )
    assert "Error: Unknown action" in err_resp
