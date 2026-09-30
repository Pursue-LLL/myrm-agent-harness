"""Cross-module path containment contract.

Spans the permission engine, executors, validators and callbacks, so it is kept
apart from the single-module unit tests.
"""

import os
from pathlib import Path

import pytest

from myrm_agent_harness.core.security.path import (
    MAX_PATH_LENGTH,
    coerce_filesystem_path,
    is_blocked_device_path,
    is_content_not_path,
    is_dangerous_path,
    is_protected_instruction_file,
    is_sensitive_file,
    is_within_boundary,
    safe_join_path,
)


class TestCanonicalPathContainmentGuard:
    """Test is_within_boundary and consolidated path containment behaviors."""

    def test_within_boundary_basic_and_nested(self, tmp_path: Path) -> None:
        from myrm_agent_harness.core.security.path import is_within_boundary

        root = tmp_path / "workspace"
        root.mkdir()
        sub = root / "src" / "deep"
        sub.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()

        assert is_within_boundary(sub, root) is True
        assert is_within_boundary(root, root) is True
        assert is_within_boundary(outside, root) is False

    def test_within_boundary_traversal_attack(self, tmp_path: Path) -> None:
        from myrm_agent_harness.core.security.path import is_within_boundary

        root = tmp_path / "workspace"
        root.mkdir()
        traversal = root / ".." / "outside"

        assert is_within_boundary(traversal, root) is False

    def test_within_boundary_symlink_escape(self, tmp_path: Path) -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        secret_dir = tmp_path / "etc"
        secret_dir.mkdir()
        symlink_target = root / "escaped_link"

        try:
            os.symlink(secret_dir, symlink_target)
        except OSError:
            pytest.skip("Symlinks not supported")

        assert is_within_boundary(symlink_target, root) is False

    def test_within_boundary_prefix_similarity_attack(self, tmp_path: Path) -> None:
        """Verify sibling directory with same prefix is strictly blocked (prevent startswith flaw)."""
        from myrm_agent_harness.core.security.path import is_within_boundary

        root = tmp_path / "workspace"
        root.mkdir()
        sibling_evil = tmp_path / "workspace_evil"
        sibling_evil.mkdir()
        evil_file = sibling_evil / "malicious.py"
        evil_file.write_text("evil")

        assert is_within_boundary(evil_file, root) is False
        assert is_within_boundary(sibling_evil, root) is False

    def test_executor_base_workspace_containment_prefix_attack(self, tmp_path: Path) -> None:
        """Verify CodeExecutor.resolve_path blocks prefix-truncation traversal attacks."""
        import asyncio

        from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor
        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            ExecutionContext,
            ExecutionResult,
        )

        ws = tmp_path / "ws"
        ws.mkdir()
        ws_evil = tmp_path / "ws_evil"
        ws_evil.mkdir()
        evil_file = ws_evil / "hack.sh"
        evil_file.write_text("malicious")

        class DummyExecutor(CodeExecutor):
            async def execute(self, context: ExecutionContext) -> ExecutionResult:
                raise NotImplementedError

            async def execute_bash(self, context: ExecutionContext) -> ExecutionResult:
                raise NotImplementedError

        executor = DummyExecutor()
        executor.bind_workspace(str(ws))

        # Relative path resolving to sibling with common prefix must be blocked
        with pytest.raises(ValueError, match="Path traversal detected"):
            asyncio.run(executor.resolve_path("../ws_evil/hack.sh"))

    def test_policy_engine_symlink_containment(self, tmp_path: Path) -> None:
        """Verify check_path_policy blocks symlink escapes pointing outside workspace."""
        from myrm_agent_harness.agent.security.checks import check_path_policy
        from myrm_agent_harness.agent.security.types import PathPolicy, PermissionAction

        ws = tmp_path / "workspace"
        ws.mkdir()
        secret_dir = tmp_path / "private_etc"
        secret_dir.mkdir()
        secret_file = secret_dir / "secret.txt"
        secret_file.write_text("classified")

        link_in_ws = ws / "symlink_secret.txt"
        try:
            os.symlink(secret_file, link_in_ws)
        except OSError:
            pytest.skip("Symlinks not supported")

        policy = PathPolicy()
        # Reading a symlink pointing outside allowed roots must require user approval (ASK)
        action, reason = check_path_policy(
            str(link_in_ws), policy, workspace_root=str(ws), require_write=False
        )
        assert action == PermissionAction.ASK
        assert "outside allowed zones" in reason

    def test_validator_forbidden_path_containment(self, tmp_path: Path) -> None:
        """Verify validator._is_forbidden_path correctly detects forbidden path boundaries."""
        from myrm_agent_harness.toolkits.code_execution.security.validator import _is_forbidden_path

        assert _is_forbidden_path("/etc/passwd") is True
        assert _is_forbidden_path("/etc/shadow") is True
        # Path with similar prefix but outside forbidden directory
        assert _is_forbidden_path("/etc/passwd_not_real") is False

    def test_acp_callback_safe_path_containment(self, tmp_path: Path) -> None:
        """Verify acp_callback._resolve_safe_path blocks traversal and symlink escapes."""
        from myrm_agent_harness.toolkits.acp.runtime.acp_callback import _resolve_safe_path

        cwd = tmp_path / "app"
        cwd.mkdir()
        inner_file = cwd / "index.js"
        inner_file.write_text("console.log('hi');")

        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        outside_file = outside_dir / "secret.key"
        outside_file.write_text("key")

        # In-bounds relative path succeeds
        assert _resolve_safe_path("index.js", str(cwd)) == inner_file.resolve()
        # Directory traversal fails
        assert _resolve_safe_path("../outside/secret.key", str(cwd)) is None

        # Symlink pointing outside cwd fails
        link = cwd / "link_out.key"
        try:
            os.symlink(outside_file, link)
            assert _resolve_safe_path("link_out.key", str(cwd)) is None
        except OSError:
            pass

    def test_skill_path_filter_containment(self, tmp_path: Path) -> None:
        """Verify is_under_disabled_skill_root accurately blocks paths under disabled roots."""
        from myrm_agent_harness.agent.meta_tools.file_search.skill_path_filter import (
            is_under_disabled_skill_root,
        )

        disabled_root = str(tmp_path / "skills" / "unsafe_skill")
        os.makedirs(disabled_root, exist_ok=True)
        inside_path = os.path.join(disabled_root, "actions", "run.py")
        outside_path = str(tmp_path / "skills" / "unsafe_skill_other" / "run.py")

        assert is_under_disabled_skill_root(inside_path, [disabled_root]) is True
        assert is_under_disabled_skill_root(outside_path, [disabled_root]) is False

class TestContentNotPathDisambiguation:
    """Test is_content_not_path() and safe isolation of text/code content from path checks."""

    def test_normal_paths_not_identified_as_content(self) -> None:
        assert is_content_not_path("/etc/passwd") is False
        assert is_content_not_path("src/core/security.py") is False
        assert is_content_not_path("./relative/path/to/file.txt") is False

    def test_multiline_strings_identified_as_content(self) -> None:
        multiline_snippet = "def hello():\n    return 'world'"
        assert is_content_not_path(multiline_snippet) is True
        assert is_content_not_path("line1\r\nline2") is True

    def test_code_fences_identified_as_content(self) -> None:
        markdown_code = "```python\nprint('hello')\n```"
        assert is_content_not_path(markdown_code) is True

    def test_oversized_text_identified_as_content(self) -> None:
        huge_text = "a" * (MAX_PATH_LENGTH + 10)
        assert is_content_not_path(huge_text) is True

    def test_coerce_filesystem_path_rejects_content(self) -> None:
        assert coerce_filesystem_path("def foo():\n    pass") is None
        assert coerce_filesystem_path("```python\nx = 1\n```") is None
        assert coerce_filesystem_path("x" * (MAX_PATH_LENGTH + 1)) is None

    def test_path_guards_safely_ignore_content_without_crashing(self) -> None:
        content_with_dangerous_pattern = "Review /etc/passwd and config\nMore content here"
        # Should cleanly return False instead of raising File name too long or OSError
        assert is_dangerous_path(content_with_dangerous_pattern) is False
        assert is_blocked_device_path(content_with_dangerous_pattern) is False
        assert is_sensitive_file(content_with_dangerous_pattern) is False
        assert is_protected_instruction_file(content_with_dangerous_pattern) is False

    def test_safe_join_path_raises_on_content(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid path: content or multiline string"):
            safe_join_path(tmp_path, "def main():\n    print('fail')")

    def test_evidence_readonly_file_detection(self) -> None:
        from myrm_agent_harness.core.security.path import is_evidence_readonly_file

        assert is_evidence_readonly_file("evidence/fact_check.pdf") is True
        assert is_evidence_readonly_file("/workspace/sessions/s1/evidence/interview.docx") is True
        assert is_evidence_readonly_file("user_inputs/dataset.csv") is True
        assert is_evidence_readonly_file(".evidence/doc.txt") is True
        assert is_evidence_readonly_file("working/temp.txt") is False
        assert is_evidence_readonly_file("artifacts/final.pdf") is False
        assert is_evidence_readonly_file("src/main.py") is False
