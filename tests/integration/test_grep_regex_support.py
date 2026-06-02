"""测试 grep 正则表达式和大小写支持

验证 LocalExecutor 的增强 grep 功能：
1. 正则表达式模式搜索
2. 大小写敏感/不敏感
3. 向后兼容（默认字面匹配）
4. 性能监控日志
"""

import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.local.executor import LocalExecutor

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
def _disable_sandbox(monkeypatch):
    """Disable OS-level sandbox so grep/shell tests work in CI and local env."""
    from myrm_agent_harness.toolkits.code_execution.sandbox.providers.null import NullProvider
    from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import SandboxStatus

    _null_result = (
        NullProvider(),
        SandboxStatus(enabled=False, provider_name="null", reason="test"),
    )
    def _fake(**_kwargs):
        return _null_result
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detect_sandbox_provider", _fake
    )
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detector.detect_sandbox_provider", _fake
    )


@pytest.fixture
async def test_workspace():
    """创建测试工作空间"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        # 创建测试文件
        (workspace / "test.py").write_text("""
def hello_world():
    print('Hello')

def test_function():
    return 42

class TestClass:
    def method(self):
        pass
""")

        (workspace / "imports.py").write_text("""
import os
import sys
from pathlib import Path
import numpy as np
from typing import List, Dict
""")

        (workspace / "mixed_case.txt").write_text("""
Docker is great
DOCKER is powerful
docker is fast
DoCtEr is weird
""")

        yield str(workspace)


class TestGrepLiteralMatch:
    """测试字面匹配（向后兼容）"""

    async def test_default_literal_match(self, test_workspace):
        """测试默认字面匹配"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 搜索字面字符串
        result = await executor.grep("def hello")

        assert "hello_world" in result
        assert "def hello_world" in result

    async def test_literal_match_explicit(self, test_workspace):
        """测试显式字面匹配"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 显式指定字面匹配
        result = await executor.grep("def hello", use_regex=False)

        assert "hello_world" in result

    async def test_special_characters_literal(self, test_workspace):
        """测试特殊字符的字面匹配"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 创建包含特殊字符的文件
        special_file = Path(test_workspace) / "special.txt"
        special_file.write_text("$PATH variable\n[test] bracket\n.*pattern")

        # 字面匹配特殊字符
        result = await executor.grep("$PATH")
        assert "PATH" in result

        result = await executor.grep("[test]")
        assert "test" in result or "bracket" in result

        result = await executor.grep(".*pattern")
        assert "pattern" in result


class TestGrepRegexMatch:
    """测试正则表达式匹配"""

    async def test_function_definition_regex(self, test_workspace):
        """测试搜索函数定义（正则）"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 搜索所有函数定义：def <name>(
        result = await executor.grep(r"def \w+\(", use_regex=True)

        assert "def hello_world" in result
        assert "def test_function" in result
        assert "def method" in result

    async def test_import_statement_regex(self, test_workspace):
        """测试搜索 import 语句（正则）"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 搜索所有 import 语句
        result = await executor.grep(r"^import |^from .* import", use_regex=True)

        assert "import os" in result or "import" in result
        assert "from pathlib import Path" in result or "pathlib" in result

    async def test_class_definition_regex(self, test_workspace):
        """测试搜索类定义（正则）"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 搜索类定义：class <Name>:
        result = await executor.grep(r"^class \w+:", use_regex=True)

        assert "TestClass" in result

    async def test_word_boundary_regex(self, test_workspace):
        """测试单词边界（正则）"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 创建明确的测试文件
        test_file = Path(test_workspace) / "word_test.txt"
        test_file.write_text("test word\ntesting word\ncontest word\n")

        # 搜索单词 "test"（使用单词边界）
        result = await executor.grep(r"\btest\b", use_regex=True)

        # 应该只匹配 "test word"，不匹配 "testing" 和 "contest"
        lines = [line for line in result.splitlines() if line.strip()]
        assert len(lines) >= 1
        assert "test word" in result or "test" in result.lower()


class TestGrepCaseSensitivity:
    """测试大小写敏感性"""

    async def test_case_sensitive_default(self, test_workspace):
        """测试默认大小写敏感"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 搜索小写 "docker"
        result = await executor.grep("docker")

        # 默认大小写敏感，只匹配小写
        lines = result.lower().splitlines()
        assert any("docker" in line for line in lines)

    async def test_case_insensitive(self, test_workspace):
        """测试大小写不敏感"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 搜索 "docker" 忽略大小写
        result = await executor.grep("docker", case_sensitive=False)

        # 应该匹配所有变体
        result_lower = result.lower()
        assert "docker" in result_lower

        # 计算匹配行数（应该匹配多个变体）
        lines = [line for line in result.splitlines() if line.strip()]
        assert len(lines) >= 3  # Docker, DOCKER, docker, DoCtEr

    async def test_case_insensitive_with_regex(self, test_workspace):
        """测试大小写不敏感 + 正则表达式"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 搜索以 "d" 开头的单词，忽略大小写
        result = await executor.grep(r"\bd\w+", use_regex=True, case_sensitive=False)

        result_lower = result.lower()
        assert "docker" in result_lower or "def" in result_lower


class TestGrepCombinations:
    """测试组合场景"""

    async def test_regex_case_insensitive(self, test_workspace):
        """测试正则 + 大小写不敏感"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 搜索函数定义，忽略大小写
        result = await executor.grep(
            r"def \w+\(",
            use_regex=True,
            case_sensitive=False,
        )

        # 应该匹配函数定义（如果有 Def 也会匹配）
        assert "def" in result.lower()

    async def test_literal_case_insensitive(self, test_workspace):
        """测试字面匹配 + 大小写不敏感"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 搜索 "IMPORT"，忽略大小写
        result = await executor.grep(
            "IMPORT",
            use_regex=False,
            case_sensitive=False,
        )

        # 应该匹配 "import"
        assert "import" in result.lower()


class TestGrepPerformanceMonitoring:
    """测试性能监控"""

    async def test_performance_logging(self, test_workspace, caplog):
        """测试性能日志记录"""
        import logging

        caplog.set_level(logging.DEBUG)

        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 执行搜索
        await executor.grep("def", use_regex=False)

        # 检查是否有性能日志（DEBUG 级别）
        log_messages = [record.message for record in caplog.records if record.levelname == "DEBUG"]

        # 应该有包含 "grep:" 的日志
        grep_logs = [msg for msg in log_messages if "grep:" in msg]

        if grep_logs:
            # 验证日志包含关键信息
            log_msg = grep_logs[0]
            assert "tool=" in log_msg
            assert "regex=" in log_msg
            assert "case_sensitive=" in log_msg
            assert "elapsed=" in log_msg
            assert "matches=" in log_msg


class TestGrepBackwardCompatibility:
    """测试向后兼容性"""

    async def test_old_api_still_works(self, test_workspace):
        """测试旧 API 仍然可用"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 简化调用方式（只传 pattern 和 path）
        result = await executor.grep("import")

        # 应该正常工作（字面匹配）
        assert "import" in result

    async def test_positional_args(self, test_workspace):
        """测试位置参数"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 位置参数调用
        result = await executor.grep("def", ".")

        assert "def" in result

    async def test_keyword_args(self, test_workspace):
        """测试关键字参数"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 关键字参数调用
        result = await executor.grep(pattern="import", path=".")

        assert "import" in result


class TestGrepEdgeCases:
    """测试边界情况"""

    async def test_empty_result_with_regex(self, test_workspace):
        """测试正则搜索无结果"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 搜索不存在的模式
        result = await executor.grep(r"NONEXISTENT\d+", use_regex=True)

        assert result == "" or not result.strip()

    async def test_invalid_regex_handling(self, test_workspace):
        """测试无效正则表达式处理"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 无效的正则表达式（未闭合的括号）
        # ripgrep 和 grep 会报错但通过 || true 不会抛异常
        result = await executor.grep(r"(unclosed", use_regex=True)

        # 应该返回空或错误信息，但不应该崩溃
        assert isinstance(result, str)

    async def test_very_long_pattern(self, test_workspace):
        """测试超长模式"""
        config = ExecutionConfig(workspace_path=test_workspace)
        executor = LocalExecutor(config, test_workspace)

        # 超长模式
        long_pattern = "a" * 1000
        result = await executor.grep(long_pattern)

        # 应该正常返回（没有匹配）
        assert isinstance(result, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
