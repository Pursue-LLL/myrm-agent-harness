"""单元测试：会话树状分支探索、文件变动足迹感知与结构化无损提炼合流套件 (Item 202)。

[INPUT]
- BranchFileOperationsTracker
- BranchSelectiveMergeEngine
- BranchFileOperations
- SelectiveMergePolicy
- FileActionKind

[OUTPUT]
- 验证分支工具调用文件足迹提取与只读/修改去重隔离
- 验证四种 SelectiveMergePolicy 策略格式化注入消息
- 验证母会话与子分支并发改动文件的冲突感知与预警
- 验证轨迹序列化、超长结果截断与完整字典序列化契约
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.branch_summary import (
    BranchFileOperations,
    BranchFileOperationsTracker,
    BranchMergeConflictWarning,
    BranchSelectiveMergeEngine,
    BranchSummaryResult,
    FileActionKind,
    SelectiveMergePolicy,
    TrackedFileOperation,
)


def test_branch_file_operations_extraction() -> None:
    """验证从消息轨迹中精准提取文件读写操作，并保证 read-only 与 modified 的互斥与排序。"""
    messages: list[dict[str, object]] = [
        {
            "role": "user",
            "content": "请重构 src/core.py 并参考 config.json",
        },
        {
            "role": "assistant",
            "content": "我先查看这两个文件。",
            "tool_calls": [
                {
                    "name": "view_file",
                    "args": {"AbsolutePath": "/workspace/config.json"},
                },
                {
                    "name": "read",
                    "args": {"path": "src/core.py"},
                },
            ],
        },
        {
            "role": "assistant",
            "content": "现在进行修改和添加新工具模块，并记录日志。",
            "tool_calls": [
                {
                    "name": "replace_file_content",
                    "args": {"TargetFile": "src/core.py"},
                },
                {
                    "name": "write_to_file",
                    "args": {"TargetFile": "src/utils.py"},
                },
                {
                    "name": "run_command",
                    "args": {
                        "CommandLine": "echo 'ok' > /workspace/build.log && cat /workspace/readme.txt"
                    },
                },
            ],
        },
    ]

    tracker = BranchFileOperationsTracker()
    raw_ops = tracker.extract_operations_from_messages(messages)
    assert len(raw_ops) >= 5

    file_ops: BranchFileOperations = tracker.compute_file_lists(raw_ops)

    # src/core.py 虽然被 read 过，但后续被修改了，因此只应出现在 modified_files 中
    assert "src/core.py" in file_ops.modified_files
    assert "src/core.py" not in file_ops.read_files

    # src/utils.py 和 /workspace/build.log 均为修改/写入
    assert "src/utils.py" in file_ops.modified_files
    assert "/workspace/build.log" in file_ops.modified_files

    # /workspace/config.json 和 /workspace/readme.txt 仅被读取
    assert "/workspace/config.json" in file_ops.read_files
    assert "/workspace/readme.txt" in file_ops.read_files

    # 验证 XML 格式化输出
    xml_output = file_ops.format_xml()
    assert "<read-files>" in xml_output
    assert "<modified-files>" in xml_output
    assert "- src/core.py" in xml_output
    assert "- /workspace/config.json" in xml_output


def test_selective_merge_policies_injection_formatting() -> None:
    """验证四种 SelectiveMergePolicy 策略下的合流注入消息生成。"""
    engine = BranchSelectiveMergeEngine()
    branch_messages: list[dict[str, object]] = [
        {"role": "user", "content": "探索采用异步管道的实现方式"},
        {
            "role": "assistant",
            "content": "已验证异步方案可行，吞吐提升 30%。",
            "tool_calls": [
                {"name": "write", "args": {"path": "pipeline_async.py"}}
            ],
        },
    ]

    # 1. FULL_SUMMARY_AND_FILES: 包含摘要及 XML 文件标签
    res_full = engine.execute_branch_compaction_and_merge(
        branch_id="branch_async_exp",
        parent_session_id="parent_sess_001",
        common_ancestor_turn_id="turn_42",
        branch_messages=branch_messages,
        merge_policy=SelectiveMergePolicy.FULL_SUMMARY_AND_FILES,
    )
    assert '<branch-summary branch_id="branch_async_exp"' in res_full.injection_message_text
    assert "已验证异步方案可行" in res_full.injection_message_text
    assert "<modified-files>" in res_full.injection_message_text
    assert "pipeline_async.py" in res_full.file_operations.modified_files

    # 2. SUMMARY_ONLY: 包含结论但无文件标签
    res_summary = engine.execute_branch_compaction_and_merge(
        branch_id="branch_async_exp",
        parent_session_id="parent_sess_001",
        common_ancestor_turn_id="turn_42",
        branch_messages=branch_messages,
        merge_policy=SelectiveMergePolicy.SUMMARY_ONLY,
    )
    assert "已验证异步方案可行" in res_summary.injection_message_text
    assert "<modified-files>" not in res_summary.injection_message_text

    # 3. MODIFIED_FILES_ONLY: 仅包含文件标签
    res_files = engine.execute_branch_compaction_and_merge(
        branch_id="branch_async_exp",
        parent_session_id="parent_sess_001",
        common_ancestor_turn_id="turn_42",
        branch_messages=branch_messages,
        merge_policy=SelectiveMergePolicy.MODIFIED_FILES_ONLY,
    )
    assert "<modified-files>" in res_files.injection_message_text
    assert "Branch Exploration Objective" not in res_files.injection_message_text

    # 4. AUDIT_DRY_RUN: 仅用于审查，不生成注入上下文
    res_dry = engine.execute_branch_compaction_and_merge(
        branch_id="branch_async_exp",
        parent_session_id="parent_sess_001",
        common_ancestor_turn_id="turn_42",
        branch_messages=branch_messages,
        merge_policy=SelectiveMergePolicy.AUDIT_DRY_RUN,
    )
    assert res_dry.injection_message_text == ""


def test_branch_conflict_detection() -> None:
    """验证当母会话在分叉后也修改了同一文件时，精准生成 HIGH 级冲突告警与应对指引。"""
    engine = BranchSelectiveMergeEngine()
    branch_messages: list[dict[str, object]] = [
        {"role": "user", "content": "在分支中重构 server.py"},
        {
            "role": "assistant",
            "content": "修改完成",
            "tool_calls": [
                {"name": "edit", "args": {"path": "server.py"}}
            ],
        },
    ]

    # 母会话在分叉后修改了 server.py 和 other.py
    parent_modified = ["server.py", "other.py"]

    result = engine.execute_branch_compaction_and_merge(
        branch_id="branch_refactor",
        parent_session_id="parent_main",
        common_ancestor_turn_id="turn_10",
        branch_messages=branch_messages,
        merge_policy=SelectiveMergePolicy.FULL_SUMMARY_AND_FILES,
        parent_modified_files_since_fork=parent_modified,
    )

    assert len(result.conflict_warnings) == 1
    warning = result.conflict_warnings[0]
    assert warning.file_path == "server.py"
    assert warning.severity == "HIGH"
    assert "Inspect git diff" in warning.resolution_hint

    # 验证注入消息中包含冲突提示标签
    assert "<conflict-warnings>" in result.injection_message_text
    assert "[CONFLICT] server.py" in result.injection_message_text


def test_branch_summary_compaction_and_serialization() -> None:
    """验证长工具结果截断、Token 估算、序列化字典及防御性兜底。"""
    engine = BranchSelectiveMergeEngine(max_tool_chars=50)

    long_output = "X" * 200
    branch_messages: list[dict[str, object]] = [
        {"role": "user", "content": "执行批处理"},
        {"role": "assistant", "content": "调用工具", "thinking": "先测试"},
        {"role": "tool", "content": long_output},
        {"role": "assistant", "content": "批处理执行成功并完成。"},
    ]

    serialized = engine.serialize_branch_trajectory(branch_messages)
    assert "[Truncated 150 characters]" in serialized

    result = engine.execute_branch_compaction_and_merge(
        branch_id="branch_batch",
        parent_session_id="parent_main",
        common_ancestor_turn_id="turn_5",
        branch_messages=branch_messages,
        custom_instructions="保留关键结论",
    )

    assert result.branch_turns_count == 4
    assert result.token_count_estimated > 0
    assert "保留关键结论" in result.summary_text

    as_dict = result.to_dict()
    assert as_dict["branch_id"] == "branch_batch"
    assert as_dict["parent_session_id"] == "parent_main"
    assert as_dict["merge_policy"] == SelectiveMergePolicy.FULL_SUMMARY_AND_FILES.value
    assert isinstance(as_dict["file_operations"], dict)
