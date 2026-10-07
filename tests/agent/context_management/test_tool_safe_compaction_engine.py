"""Tests for Tool-Safe Compaction Boundary & File Manifests Transmission Suite (Item 238)."""

from myrm_agent_harness.agent.context_management.tool_safe_compaction import (
    CutPointSafetyKind,
    FileManifests,
    SafeCompactionResult,
    ToolSafeCompactionEngine,
    evaluate_cut_point,
    extract_file_manifests,
    find_valid_cut_points,
    select_optimal_safe_cut_point,
)


def test_safe_cut_point_detection_and_tool_result_protection() -> None:
    """Verify that toolResult messages are rejected as cut points, preventing orphan 400 errors."""
    messages = [
        {"role": "user", "content": "Fetch database configuration and check user table schema."},  # 0
        {
            "role": "assistant",
            "content": "Calling read_file for config/database.json",
            "has_tool_calls": "true",
            "tool_name": "read_file",
        },  # 1
        {"role": "tool", "content": '{"host": "localhost", "port": 5432}', "tool_name": "read_file"},  # 2
        {"role": "assistant", "content": "Configuration loaded. Now examining migration schema."},  # 3
        {"role": "user", "content": "Please proceed with schema validation."},  # 4
    ]

    # Index 2 is a 'tool' result: MUST BE INVALID
    eval_tool_result = evaluate_cut_point(messages, 2)
    assert not eval_tool_result.is_valid
    assert eval_tool_result.safety == CutPointSafetyKind.UNSAFE_TOOL_RESULT

    # Index 0, 3, 4, 5 are safe boundaries
    valid_points = find_valid_cut_points(messages)
    assert 2 not in valid_points
    assert 0 in valid_points
    assert 3 in valid_points
    assert 4 in valid_points

    # Snapping index 2 must divert to safe boundary (3 or 0)
    snapped_index = select_optimal_safe_cut_point(messages, desired_index=2)
    assert snapped_index != 2
    assert snapped_index in (0, 3)


def test_file_manifests_extraction_and_transmission() -> None:
    """Verify read and modified file paths are accurately captured and survive compaction."""
    compressed_turns = [
        {
            "role": "assistant",
            "content": "Reading file: src/core/config.py and view_file: 'src/utils/logger.ts'",
            "tool_name": "read_file",
        },
        {
            "role": "tool",
            "content": "file contents of config.py",
            "tool_name": "read_file",
            "read_files": "src/core/config.py,docs/schema.md",
        },
        {
            "role": "assistant",
            "content": "Patching code: write_to_file 'src/core/database.py'",
            "tool_name": "write_file",
            "modified_files": "src/core/database.py",
        },
    ]

    manifests = extract_file_manifests(compressed_turns)
    assert "src/core/config.py" in manifests.read_files
    assert "src/utils/logger.ts" in manifests.read_files
    assert "docs/schema.md" in manifests.read_files
    assert "src/core/database.py" in manifests.modified_files
    assert manifests.total_touched_files >= 4

    engine = ToolSafeCompactionEngine()
    history = [
        {"role": "user", "content": "Initialize project configuration."},
        *compressed_turns,
        {"role": "user", "content": "Now run migrations on the database."},
    ]

    result = engine.compact_context(messages=history, desired_cut_index=4)
    assert result.cut_point_index == 4
    assert result.file_manifests.total_touched_files >= 4
    assert "[Workspace File Manifests (Survives Compaction)]" in result.compaction_summary
    assert "src/core/database.py" in result.compaction_summary
    assert "src/core/config.py" in result.compaction_summary

    # Ensure system checkpoint is the first message in compacted context
    assert result.compacted_context[0]["role"] == "system"
    assert "src/core/database.py" in result.compacted_context[0]["content"]
    # Preserved tail retains the last user request
    assert result.compacted_context[-1]["content"] == "Now run migrations on the database."


def test_end_to_end_safe_compaction_api_compliance() -> None:
    """Verify end-to-end compaction maintains atomic tool pairing and API sequence compliance."""
    engine = ToolSafeCompactionEngine()
    dialog = [
        {"role": "user", "content": "Step 1: Inspect server status."},  # 0
        {"role": "assistant", "content": "Checking status with bash tool.", "has_tool_calls": "true"},  # 1
        {"role": "tool", "content": "Server OK", "tool_name": "bash"},  # 2
        {"role": "user", "content": "Step 2: Inspect nginx logs."},  # 3
        {"role": "assistant", "content": "Reading log file.", "has_tool_calls": "true"},  # 4
        {"role": "tool", "content": "200 OK 0.05s", "tool_name": "read_file", "read_files": "/var/log/nginx.log"},  # 5
        {"role": "user", "content": "Step 3: Deploy new build."},  # 6
    ]

    # Deliberately request a cut right in the middle of tool execution (e.g. index 2 or index 5)
    result_at_2 = engine.compact_context(messages=dialog, desired_cut_index=2)
    # Must NOT cut at 2; must snap to 0 or 3
    assert result_at_2.cut_point_index != 2
    # Verify the preserved tail never starts with a dangling 'tool' result
    first_non_system = result_at_2.compacted_context[1]
    assert first_non_system["role"] != "tool"

    result_at_5 = engine.compact_context(messages=dialog, desired_cut_index=5)
    # Must NOT cut at 5; must snap to safe boundary (3 or 6)
    assert result_at_5.cut_point_index != 5
    first_tail_msg = result_at_5.compacted_context[1]
    assert first_tail_msg["role"] != "tool"
    assert "/var/log/nginx.log" in result_at_5.compaction_summary
