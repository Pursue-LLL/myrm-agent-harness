"""Tests for Protected Instruction Files Approval Gate and Persistent Prompt Injection Guard (Roadmap Item 128)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from myrm_agent_harness.agent.middlewares.approval._batch_decisions import (
    _should_block_allow_always,
)
from myrm_agent_harness.agent.security.checks import check_path_policy
from myrm_agent_harness.agent.security.path_security import (
    PROTECTED_INSTRUCTION_PATTERNS,
    is_protected_instruction_file,
)
from myrm_agent_harness.agent.security.types import (
    AccessRoot,
    PathPolicy,
    PermissionAction,
)
from myrm_agent_harness.toolkits.code_execution.security.shell_command_analyzer import (
    ThreatLevel,
    analyze_command,
    is_protected_instruction_mutation_command,
)


class TestProtectedInstructionPathDetection:
    """Verify is_protected_instruction_file matches all critical persona files and resists evasion."""

    @pytest.mark.parametrize(
        "file_path",
        [
            "AGENTS.md",
            "CLAUDE.md",
            "SOUL.md",
            "USER.md",
            ".user.md",
            "MEMORY.md",
            ".cursorrules",
            ".clinerules",
            ".windsurfrules",
            ".myrm.md",
            "myrm.md",
            ".hermes.md",
            "HERMES.md",
            ".github/copilot-instructions.md",
            ".cursor/rules/security.mdc",
            ".myrm/rules/team.md",
            "/workspace/nested/sub/AGENTS.md",
            "../other/SOUL.md",
        ],
    )
    def test_protected_files_detected(self, file_path: str) -> None:
        assert is_protected_instruction_file(file_path) is True

    @pytest.mark.parametrize(
        "case_variant",
        [
            "agents.md",
            "Agents.MD",
            "claude.md",
            "Soul.Md",
            "memory.MD",
            ".CursorRules",
            ".Myrm.MD",
        ],
    )
    def test_case_insensitive_detection(self, case_variant: str) -> None:
        assert is_protected_instruction_file(case_variant) is True

    def test_symlink_traversal_detection(self, tmp_path: Path) -> None:
        """Ensure a symlink pointing to AGENTS.md is detected via resolution."""
        target_agents_file = tmp_path / "AGENTS.md"
        target_agents_file.write_text("# Master Agent Rules")

        symlink_file = tmp_path / "harmless_notes.txt"
        os.symlink(target_agents_file, symlink_file)

        assert is_protected_instruction_file(str(symlink_file)) is True

    def test_harmless_files_not_flagged(self) -> None:
        for harmless in (
            "README.md",
            "main.py",
            "src/utils.py",
            "package.json",
            "docs/agents_guide.html",
            "memory_profiler.py",
        ):
            assert is_protected_instruction_file(harmless) is False


class TestPathPolicyCheckGate:
    """Verify check_path_policy enforces PermissionAction.ASK for writes to protected instruction files."""

    def test_read_protected_instruction_file_allowed(self, tmp_path: Path) -> None:
        ws = str(tmp_path)
        policy = PathPolicy(forbidden_paths=(), access_roots=())
        action, reason = check_path_policy(
            f"{ws}/AGENTS.md",
            policy,
            workspace_root=ws,
            require_write=False,
        )
        assert action == PermissionAction.ALLOW
        assert reason == ""

    def test_write_protected_instruction_file_triggers_ask(self, tmp_path: Path) -> None:
        ws = str(tmp_path)
        policy = PathPolicy(forbidden_paths=(), access_roots=())
        action, reason = check_path_policy(
            f"{ws}/AGENTS.md",
            policy,
            workspace_root=ws,
            require_write=True,
        )
        assert action == PermissionAction.ASK
        assert "Protected instruction file write requires human approval" in reason

    def test_relative_path_write_triggers_ask(self, tmp_path: Path) -> None:
        ws = str(tmp_path)
        policy = PathPolicy(forbidden_paths=(), access_roots=())
        action, reason = check_path_policy(
            ".cursorrules",
            policy,
            workspace_root=ws,
            require_write=True,
        )
        assert action == PermissionAction.ASK
        assert "Protected instruction file write requires human approval" in reason


class TestShellMutationAnalysis:
    """Verify Shell command analyzer catches indirect mutations against protected instruction files."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo 'hacked' > AGENTS.md",
            "cat payload.txt >> SOUL.md",
            "echo 'override' > USER.md",
            "rm -f .user.md",
            "sed -i 's/safe/unsafe/' .cursorrules",
            "tee MEMORY.md < injection.txt",
            "rm -f .clinerules",
            "mv mal.md AGENTS.md",
            "cp backdoor.md .myrm.md",
        ],
    )
    def test_shell_mutation_detected(self, cmd: str) -> None:
        assert is_protected_instruction_mutation_command(cmd) is True
        threats = analyze_command(cmd)
        threat_cats = [t.category for t in threats]
        assert "protected_instruction_mutation" in threat_cats
        threat = next(t for t in threats if t.category == "protected_instruction_mutation")
        assert threat.level == ThreatLevel.ESCALATE

    def test_benign_shell_read_not_flagged_as_mutation(self) -> None:
        assert is_protected_instruction_mutation_command("cat AGENTS.md") is False
        assert is_protected_instruction_mutation_command("head -n 20 SOUL.md") is False
        assert is_protected_instruction_mutation_command("grep 'rule' .cursorrules") is False


class TestApprovalFlowPermanentExemptionGuard:
    """Verify _should_block_allow_always forbids 'Always Allow' for protected instruction mutations."""

    def test_blocks_allow_always_on_file_write_tool(self) -> None:
        tool_call = {
            "name": "file_write_tool",
            "args": {"path": "AGENTS.md", "content": "injected instructions"},
        }
        assert _should_block_allow_always(tool_call, extra_ctx=None) is True

    def test_blocks_allow_always_with_protected_instruction_context(self) -> None:
        tool_call = {
            "name": "edit_file",
            "args": {"path": "safe.py"},
        }
        extra_ctx = {"protected_instruction": True}
        assert _should_block_allow_always(tool_call, extra_ctx=extra_ctx) is True

    def test_blocks_allow_always_on_shell_mutation_command(self) -> None:
        tool_call = {
            "name": "bash_code_execute_tool",
            "args": {"command": "echo malicious > SOUL.md"},
        }
        assert _should_block_allow_always(tool_call, extra_ctx=None) is True
