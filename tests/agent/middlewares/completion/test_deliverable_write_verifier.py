"""Unit tests for CompletionGuard deliverable write claim and unwritten deliverable verifier."""

from __future__ import annotations

from myrm_agent_harness.agent.middlewares.completion.deliverable_write_verifier import (
    check_deliverable_write_claim,
    check_unwritten_deliverable,
    check_unwritten_deliverables,
    detect_claimed_file_write,
    detect_unwritten_deliverables,
    has_successful_file_write_calls,
)
from myrm_agent_harness.agent.security.guards.loop_guard.types import (
    CallRecord,
    SuccessLevel,
)


def _record(tool_name: str, level: SuccessLevel = SuccessLevel.FULL_SUCCESS) -> CallRecord:
    return CallRecord(
        tool_name=tool_name,
        args_hash="h",
        args={"path": "/workspace/x.py"},
        success_level=level,
    )


class TestDetectClaimedFileWrite:
    def test_empty_text_false(self) -> None:
        assert detect_claimed_file_write("") is False
        assert detect_claimed_file_write("   ") is False

    def test_no_claim_phrase_false(self) -> None:
        assert detect_claimed_file_write("Here is the result of the analysis.") is False

    def test_claim_phrase_without_path_false(self) -> None:
        assert detect_claimed_file_write("The file was saved.") is False

    def test_english_claim_with_backtick_path_true(self) -> None:
        assert detect_claimed_file_write("Saved to `output/report.md`.") is True

    def test_english_claim_with_workspace_path_true(self) -> None:
        assert detect_claimed_file_write("wrote to workspace/data/result.csv") is True

    def test_english_claim_with_extension_path_true(self) -> None:
        assert detect_claimed_file_write("Created the file data/report.pdf") is True

    def test_chinese_claim_true(self) -> None:
        assert detect_claimed_file_write("结果已保存到 `analysis/report.md`") is True
        assert detect_claimed_file_write("文件已生成：output/summary.xlsx") is True

    def test_case_insensitive(self) -> None:
        assert detect_claimed_file_write("WROTE TO `out.txt`") is True


class TestHasSuccessfulFileWriteCalls:
    def test_empty_records_false(self) -> None:
        assert has_successful_file_write_calls([]) is False

    def test_successful_file_write_true(self) -> None:
        assert has_successful_file_write_calls([_record("file_write_tool")]) is True

    def test_non_failure_edit_true(self) -> None:
        assert has_successful_file_write_calls([_record("file_edit_tool", SuccessLevel.PARTIAL_SUCCESS)]) is True

    def test_failed_write_false(self) -> None:
        assert has_successful_file_write_calls([_record("file_write_tool", SuccessLevel.FAILURE)]) is False

    def test_non_write_tool_false(self) -> None:
        assert has_successful_file_write_calls([_record("bash_code_execute_tool")]) is False

    def test_mixed_records_finds_write(self) -> None:
        records = [
            _record("bash_code_execute_tool"),
            _record("file_write_tool"),
            _record("file_edit_tool", SuccessLevel.FAILURE),
        ]
        assert has_successful_file_write_calls(records) is True


class TestCheckDeliverableWriteClaim:
    def test_no_claim_returns_none(self) -> None:
        assert check_deliverable_write_claim("Just answering.", []) is None

    def test_claim_with_successful_write_returns_none(self) -> None:
        assert check_deliverable_write_claim("Saved to `out/report.md`", [_record("file_write_tool")]) is None

    def test_claim_without_write_returns_reason(self) -> None:
        reason = check_deliverable_write_claim("Saved to `out/report.md`", [])
        assert reason is not None
        assert "no successful file_write_tool" in reason


class TestDetectUnwrittenDeliverables:
    def test_empty_text_returns_empty(self) -> None:
        assert detect_unwritten_deliverables("") == []
        assert detect_unwritten_deliverables("Just simple text without code blocks.") == []

    def test_ignored_languages_skipped(self) -> None:
        content = "```plaintext\nLine 1\nLine 2\nLine 3\nLine 4\nLine 5\n```"
        assert detect_unwritten_deliverables(content) == []

    def test_bash_commands_only_skipped(self) -> None:
        content = "```bash\ncd my-project\npip install -r requirements.txt\npython main.py\n```"
        assert detect_unwritten_deliverables(content) == []

    def test_pedagogical_snippet_allowed_under_explanation_intent(self) -> None:
        # A 10-line python snippet explaining recursion should not trigger unwritten block
        code = (
            "```python\n"
            "def factorial(n):\n"
            "    if n <= 1:\n"
            "        return 1\n"
            "    return n * factorial(n - 1)\n"
            "\n"
            "print(factorial(5))\n"
            "```"
        )
        assert detect_unwritten_deliverables(code, latest_user_text="什么是递归算法？请解释一下原理") == []
        assert detect_unwritten_deliverables(code, latest_user_text="给个 demo 看看，不用保存") == []
        assert detect_unwritten_deliverables(code, latest_user_text="just show an example snippet, do not save") == []
        assert detect_unwritten_deliverables(code, latest_user_text="仅供参考的示例片段") == []

    def test_explicit_filename_hint_detected(self) -> None:
        code = (
            "```python\n"
            "# filename: app/server.py\n"
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "\n"
            "@app.get('/')\n"
            "def root():\n"
            "    return {'status': 'ok'}\n"
            "```"
        )
        result = detect_unwritten_deliverables(code)
        assert len(result) == 1
        assert result[0].filename_hint == "app/server.py"
        assert result[0].language == "python"
        assert result[0].suggested_ext == ".py"

    def test_explicit_deliverable_intent_detects_substantive_code(self) -> None:
        code_lines = [f"x_{i} = {i}" for i in range(15)]
        code = f"```typescript\n{chr(10).join(code_lines)}\n```"
        result = detect_unwritten_deliverables(code, latest_user_text="请实现并输出完整的数据模型代码")
        assert len(result) == 1
        assert result[0].language == "typescript"
        assert result[0].line_count >= 12


class TestCheckUnwrittenDeliverables:
    def test_with_successful_write_returns_none(self) -> None:
        code = "```python\n# filename: script.py\nprint('hello')\nprint('world')\nprint('test')\nprint('more')\nprint('lines')\n```"
        reason, items = check_unwritten_deliverables(
            content=code,
            records=[_record("file_write_tool")],
        )
        assert reason is None
        assert items == []
        assert check_unwritten_deliverable(content=code, records=[_record("file_write_tool")]) is None

    def test_with_failed_write_call_blocks(self) -> None:
        code = "```python\n# filename: script.py\nprint('hello')\nprint('world')\nprint('test')\nprint('more')\nprint('lines')\n```"
        # If write tool failed with FAILURE level, it must not be considered a successful write
        failed_record = _record("file_write_tool", level=SuccessLevel.FAILURE)
        reason, items = check_unwritten_deliverables(
            content=code,
            records=[failed_record],
        )
        assert reason is not None
        assert "Substantial unpersisted deliverables detected" in reason
        assert len(items) == 1

    def test_without_write_returns_reason_and_items(self) -> None:
        code = "```python\n# filename: script.py\nprint('hello')\nprint('world')\nprint('test')\nprint('more')\nprint('lines')\n```"
        reason, items = check_unwritten_deliverables(
            content=code,
            records=[],
        )
        assert reason is not None
        assert "Substantial unpersisted deliverables detected" in reason
        assert len(items) == 1
        assert items[0].filename_hint == "script.py"

        single_reason = check_unwritten_deliverable(content=code, records=[])
        assert single_reason == reason

    def test_multiple_code_blocks_aggregated(self) -> None:
        code_1 = "```python\n# filename: a.py\nprint(1)\nprint(2)\nprint(3)\nprint(4)\nprint(5)\n```"
        code_2 = "```typescript\n// filename: b.ts\nconst x = 1;\nconst y = 2;\nconst z = 3;\nconst w = 4;\nconst v = 5;\n```"
        content = f"Here are two files:\n{code_1}\nand\n{code_2}"
        reason, items = check_unwritten_deliverables(
            content=content,
            records=[],
        )
        assert reason is not None
        assert len(items) == 2
        assert items[0].filename_hint == "a.py"
        assert items[1].filename_hint == "b.ts"
        assert "a.py" in reason
        assert "b.ts" in reason

    def test_pedagogical_with_full_executable_structure_detected(self) -> None:
        # If user asks educational question, but assistant produces a huge 30-line full entrypoint file,
        # it should be recognized as a substantive deliverable.
        full_app_lines = [f"line_{i} = {i}" for i in range(25)]
        code = (
            "```python\n"
            + "\n".join(full_app_lines)
            + "\nif __name__ == '__main__':\n"
            + "    print('run')\n"
            + "```"
        )
        reason, items = check_unwritten_deliverables(
            content=code,
            records=[],
            latest_user_text="请解释一下 Python 程序的结构是什么原理？",
        )
        assert reason is not None
        assert len(items) == 1
        assert items[0].language == "python"

    def test_structured_data_csv_wide_table_detected_by_byte_density(self) -> None:
        # A 7-line CSV with a header and 6 wide rows (> 300 bytes) should be detected
        header = "id,name,email,company,role,department,location,phone,created_at\n"
        rows = "".join(
            f"usr_{i},Alice_{i},alice_{i}@example.com,VortexAI,Engineer,DevOps,Beijing,1380013800{i},2026-09-05T12:00:00Z\n"
            for i in range(6)
        )
        csv_block = f"```csv\n{header}{rows}```"
        reason, items = check_unwritten_deliverables(
            content=f"Here is your exported data:\n{csv_block}",
            records=[],
            latest_user_text="请整理用户数据并输出为 CSV 格式",
        )
        assert reason is not None
        assert len(items) == 1
        assert items[0].language == "csv"
        assert items[0].suggested_ext == ".csv"

    def test_structured_data_compact_json_detected_by_byte_density(self) -> None:
        # A 7-line JSON config (> 250 bytes) under explicit deliverable intent
        json_content = (
            "{\n"
            '  "service_name": "production-api-gateway",\n'
            '  "environment": "production-vortex-cloud",\n'
            '  "listen_port": 8080,\n'
            '  "endpoints": ["/api/v1/health", "/api/v1/auth", "/api/v1/metrics", "/api/v1/query"],\n'
            '  "rate_limit_per_minute": 1200,\n'
            '  "tls_enabled": true\n'
            "}\n"
        )
        json_block = f"```json\n{json_content}\n```"
        reason, items = check_unwritten_deliverables(
            content=f"Configuration file generated:\n{json_block}",
            records=[],
            latest_user_text="请生成网关服务配置文件 config.json",
        )
        assert reason is not None
        assert len(items) == 1
        assert items[0].language == "json"

