"""单元测试：全历史对话流原生 FTS5 全文索引与按需零损精准回溯工具套件 (Item 208).

[INPUT]
- SessionHistoryFTS5SearchEngine
- SessionSearchQuery
- SessionSearchHit
- SessionSearchResult
- SessionSearchScope
- SearchRoleFilter

[OUTPUT]
- 验证 SQLite FTS5 虚拟表全文搜索与高亮片段提取
- 验证大报文被压缩后通过 verbatim 表按需零损精准召回
- 验证按角色、轮次范围及跨会话范围过滤
- 验证来源事实引用标记生成与字典序列化
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.session_search import (
    SearchRoleFilter,
    SessionHistoryFTS5SearchEngine,
    SessionSearchHit,
    SessionSearchQuery,
    SessionSearchResult,
    SessionSearchScope,
)


def test_fts5_indexing_and_keyword_search() -> None:
    """验证 FTS5 虚拟表全文索引构建、关键词与前缀查询、以及 BM25 相关度排序。"""
    engine = SessionHistoryFTS5SearchEngine(db_path=":memory:")
    sid = "session_fts_001"

    engine.index_message(
        message_id="msg_01",
        session_id=sid,
        turn_index=1,
        role="user",
        content="请连接位于端口 8443 的安全数据库集群并检查状态",
    )
    engine.index_message(
        message_id="msg_02",
        session_id=sid,
        turn_index=2,
        role="assistant",
        content="我将执行网络探针命令测试 8443 端口连接。",
    )
    engine.index_message(
        message_id="msg_03",
        session_id=sid,
        turn_index=3,
        role="tool",
        tool_name="run_command",
        content="ConnectionError: target host 192.168.1.50:8443 connection refused with errno 111",
    )

    # 1. 搜索特定端口号和错误关键字
    query = SessionSearchQuery(
        query="8443 ConnectionError",
        session_id=sid,
        scope=SessionSearchScope.CURRENT_SESSION,
    )
    res = engine.search_history(query)

    assert res.total_hits >= 1
    hit = res.hits[0]
    assert hit.message_id == "msg_03"
    assert hit.turn_index == 3
    assert hit.role == "tool"
    assert hit.tool_name == "run_command"
    assert "8443" in hit.snippet
    assert hit.relevance_score > 0.0

    engine.close()


def test_verbatim_full_output_recovery() -> None:
    """验证长报文按需调取：即便上下文做了截断，底层仍能原样返回未删减内容。"""
    engine = SessionHistoryFTS5SearchEngine(db_path=":memory:")
    sid = "session_fts_002"

    huge_content = "INIT_HEADER\n" + ("LOG_TRACE_ENTRY_LINE\n" * 200) + "COMMIT_HASH=a1b2c3d4e5f6\nDONE"
    engine.index_message(
        message_id="msg_huge",
        session_id=sid,
        turn_index=8,
        role="tool",
        tool_name="git_log",
        content=huge_content,
    )

    # 1. 使用 include_full_output=True 检索
    query = SessionSearchQuery(
        query="COMMIT_HASH",
        session_id=sid,
        include_full_output=True,
    )
    res = engine.search_history(query)

    assert res.total_hits == 1
    assert res.hits[0].full_content is not None
    assert "a1b2c3d4e5f6" in res.hits[0].full_content
    assert len(res.hits[0].full_content) == len(huge_content)

    # 2. 单独通过 fetch_verbatim_message 调取
    verbatim_fetched = engine.fetch_verbatim_message("msg_huge")
    assert verbatim_fetched == huge_content

    # 3. 未找到时的防御性返回
    not_found = engine.fetch_verbatim_message("non_existent_id")
    assert not_found is None

    engine.close()


def test_scope_role_and_turn_range_filters() -> None:
    """验证按角色、轮次区间与跨会话作用域的多维复合过滤。"""
    engine = SessionHistoryFTS5SearchEngine(db_path=":memory:")

    # 插入 session_A
    engine.index_message("m_a1", "sess_A", 1, "user", "关于算法优化的提问")
    engine.index_message("m_a2", "sess_A", 2, "assistant", "算法优化建议采用动态规划")
    engine.index_message("m_a5", "sess_A", 5, "tool", "算法测试耗时 12ms", tool_name="benchmark")

    # 插入 session_B
    engine.index_message("m_b1", "sess_B", 1, "user", "算法优化关于内存控制")

    # 1. 限定当前会话 sess_A，仅搜 tool 角色
    q_tool_only = SessionSearchQuery(
        query="算法",
        session_id="sess_A",
        scope=SessionSearchScope.CURRENT_SESSION,
        role=SearchRoleFilter.TOOL,
    )
    res_tool = engine.search_history(q_tool_only)
    assert res_tool.total_hits == 1
    assert res_tool.hits[0].message_id == "m_a5"

    # 2. 轮次区间限定 turn_index in [1, 2]
    q_turn_range = SessionSearchQuery(
        query="算法",
        session_id="sess_A",
        turn_min=1,
        turn_max=2,
    )
    res_range = engine.search_history(q_turn_range)
    assert res_range.total_hits == 2
    for h in res_range.hits:
        assert h.turn_index in (1, 2)

    # 3. 跨全会话范围搜索
    q_all = SessionSearchQuery(
        query="算法",
        session_id="sess_A",
        scope=SessionSearchScope.CROSS_SESSION_ALL,
    )
    res_all = engine.search_history(q_all)
    assert res_all.total_hits == 4

    engine.close()


def test_citation_tag_and_json_serialization() -> None:
    """验证来源事实引用标记生成与结果字典序列化契约。"""
    engine = SessionHistoryFTS5SearchEngine(db_path=":memory:")
    sid = "session_fts_004"

    engine.index_message(
        message_id="msg_cite",
        session_id=sid,
        turn_index=15,
        role="tool",
        tool_name="cat",
        content="TARGET_CONFIG_VALUE=PROD_STAGING",
    )

    query = SessionSearchQuery(query="TARGET_CONFIG_VALUE", session_id=sid)
    res: SessionSearchResult = engine.search_history(query)

    assert res.total_hits == 1
    hit = res.hits[0]
    assert hit.citation_tag == "[来源: 第 15 轮 tool (cat)]"

    as_dict = res.to_dict()
    assert as_dict["query"] == "TARGET_CONFIG_VALUE"
    assert as_dict["total_hits"] == 1
    assert as_dict["search_duration_ms"] >= 0.0
    assert len(as_dict["hits"]) == 1
    assert as_dict["hits"][0]["citation_tag"] == "[来源: 第 15 轮 tool (cat)]"

    engine.close()
