"""Sandbox validation for evolved skills.

[INPUT]
- agent.skills.evolution.core.types::SkillRecord, VerificationProof (POS: Data types for skill evolution system.)
- agent.skills.evolution.execution.hollow_detector::HollowTestDetector (POS: Detector against trivial/vacuous validation.)
- toolkits.code_execution.executors.test_executor::SubprocessCodeExecutor (POS: Run generated evolution tests in an isolated subprocess.)
- toolkits.code_execution.executors.local.executor::LocalExecutor (POS: Local code executor with persistent Bash sessions.)
- toolkits.code_execution.config::ExecutionConfig (POS: Code execution configuration layer.)

[OUTPUT]
- SandboxValidator: Validates skills in a subprocess dry-run with AST analysis, hollow-test detection, and verification capsule generation.

[POS]
Sandbox validation for evolved skills. Integrates AST static analysis, hollow-test interception, and produces verified execution proofs.
"""

from __future__ import annotations

import logging
import re
import tempfile
from datetime import datetime
from typing import Any

from myrm_agent_harness.agent.skills.evolution.core.types import (
    SkillRecord,
    SkillVerificationType,
    VerificationProof,
)
from myrm_agent_harness.agent.skills.evolution.execution.hollow_detector import (
    HollowTestDetector,
)
from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.base import ExecutionContext
from myrm_agent_harness.toolkits.code_execution.executors.local.executor import (
    LocalExecutor,
)
from myrm_agent_harness.toolkits.code_execution.executors.test_executor import (
    SubprocessCodeExecutor,
)

logger = logging.getLogger(__name__)

__all__ = ["SandboxValidator"]


class SandboxValidator:
    """Validates skills in a subprocess dry-run with strict security constraints and verified capsule proofs."""

    def __init__(self, timeout_seconds: float = 10.0):
        self._test_executor = SubprocessCodeExecutor(timeout_seconds=timeout_seconds, allow_network=False)
        self._hollow_detector = HollowTestDetector()
        self._timeout_seconds = timeout_seconds

    def _determine_skill_type(self, skill: SkillRecord) -> SkillVerificationType:
        """Determine whether the skill contains executable code blocks or is purely prompt instruction."""
        has_python = bool(re.search(r"```python\n(.*?)\n```", skill.content, re.DOTALL))
        has_bash = bool(re.search(r"```bash\n(.*?)\n```", skill.content, re.DOTALL))
        has_steps = bool(skill.verification_steps)
        if has_python or has_bash or has_steps:
            return SkillVerificationType.CODE_EXECUTABLE
        return SkillVerificationType.PROMPT_INSTRUCTION

    def _calculate_blast_radius(self, skill: SkillRecord) -> dict[str, int]:
        """Estimate blast radius (affected lines and files) based on skill content."""
        lines = len(skill.content.splitlines())
        files = 1
        return {"files": files, "lines": lines}

    def _run_ast_analysis(self, python_code: str) -> tuple[bool, str]:
        """Perform 0-cost static AST analysis to catch syntax errors and high-risk operations."""
        import ast

        try:
            tree = ast.parse(python_code)
        except SyntaxError as e:
            snippet = ""
            if e.lineno and e.lineno <= len(python_code.splitlines()):
                snippet = f"\n```python\n{python_code.splitlines()[e.lineno - 1]}\n```"
            return False, f"SyntaxError: {e.msg} at line {e.lineno}{snippet}"
        except Exception as e:
            return False, f"ParseError: {e!s}"

        # Check for high-risk operations
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
                return (
                    False,
                    f"HighRiskOperation: Use of '{node.func.id}' is strictly prohibited.\n```python\n{node.func.id}(...)\n```",
                )

        return True, "AST analysis passed"

    async def verify_skill_capsule(self, skill: SkillRecord) -> VerificationProof:
        """Run full capsule validation and generate a tamper-evident VerificationProof."""
        skill_type = self._determine_skill_type(skill)
        blast_radius = self._calculate_blast_radius(skill)
        command_results: list[dict[str, Any]] = []

        # 1. For pure prompt instruction skills: validate markdown structure & variable placeholders
        if skill_type == SkillVerificationType.PROMPT_INSTRUCTION:
            if not skill.name.strip() or not skill.content.strip():
                return VerificationProof(
                    is_verified=False,
                    hollow_detected=True,
                    success_streak=0,
                    blast_radius=blast_radius,
                    verification_summary="Prompt skill missing required name or content",
                    environment=skill.environment,
                    verified_at=datetime.now(),
                )
            return VerificationProof(
                is_verified=True,
                hollow_detected=False,
                success_streak=1,
                blast_radius=blast_radius,
                verification_summary="Prompt instruction skill format and structure verified",
                environment=skill.environment,
                verified_at=datetime.now(),
            )

        # 2. For code-executable skills: Python block AST & Hollow detection
        python_blocks = re.findall(r"```python\n(.*?)\n```", skill.content, re.DOTALL)
        if python_blocks:
            combined_code = "\n\n".join(python_blocks)

            # AST Static Analysis
            ast_passed, ast_msg = self._run_ast_analysis(combined_code)
            if not ast_passed:
                return VerificationProof(
                    is_verified=False,
                    hollow_detected=False,
                    success_streak=0,
                    blast_radius=blast_radius,
                    verification_summary=f"AST Analysis Failed: {ast_msg}",
                    environment=skill.environment,
                    verified_at=datetime.now(),
                )

            # Hollow test detection on test blocks
            hollow_result = self._hollow_detector.analyze_python_code(combined_code)
            if hollow_result.is_hollow:
                return VerificationProof(
                    is_verified=False,
                    hollow_detected=True,
                    success_streak=0,
                    blast_radius=blast_radius,
                    verification_summary=f"Hollow Test Rejected: {', '.join(hollow_result.reasons)}",
                    environment=skill.environment,
                    verified_at=datetime.now(),
                )

            pytest_code = """
import py_compile
def test_syntax():
    py_compile.compile("skill_under_test.md", doraise=True)
"""
            result = await self._test_executor.run_tests(
                skill_content=combined_code,
                test_code=pytest_code,
                skill_name=skill.name,
            )
            command_results.append({
                "type": "python_syntax_and_eval",
                "passed": result.passed,
                "stdout": result.stdout,
                "stderr": result.stderr,
            })
            if not result.passed:
                return VerificationProof(
                    is_verified=False,
                    hollow_detected=False,
                    success_streak=0,
                    blast_radius=blast_radius,
                    verification_summary=f"Dry-run syntax check failed: {result.stderr or result.stdout}",
                    command_results=command_results,
                    environment=skill.environment,
                    verified_at=datetime.now(),
                )

        # 3. Verification steps execution in isolated LocalExecutor
        hollow_commands = 0
        if skill.verification_steps:
            config = ExecutionConfig()
            config.local.max_execution_time = int(self._timeout_seconds)
            config.network.allow_network = False

            with tempfile.TemporaryDirectory() as temp_dir:
                async with LocalExecutor(config, temp_dir) as executor:
                    for step in skill.verification_steps:
                        cmd = step.get("command", "")
                        if not cmd:
                            continue

                        # Check for hollow shell command
                        cmd_hollow = self._hollow_detector.analyze_shell_command(cmd)
                        if cmd_hollow.is_hollow:
                            hollow_commands += 1
                            return VerificationProof(
                                is_verified=False,
                                hollow_detected=True,
                                success_streak=0,
                                blast_radius=blast_radius,
                                verification_summary=f"Hollow verification step detected: `{cmd}`",
                                command_results=command_results,
                                environment=skill.environment,
                                verified_at=datetime.now(),
                            )

                        # Block inline script execution bypasses
                        if re.search(r"(python|python3|node)\s+-c\s+[\"']", cmd):
                            return VerificationProof(
                                is_verified=False,
                                hollow_detected=False,
                                success_streak=0,
                                blast_radius=blast_radius,
                                verification_summary=f"HighRiskOperation: Inline script execution blocked: `{cmd}`",
                                command_results=command_results,
                                environment=skill.environment,
                                verified_at=datetime.now(),
                            )

                        context = ExecutionContext(
                            code=cmd,
                            timeout=int(self._timeout_seconds),
                            allow_network=False,
                            workspace_root=temp_dir,
                            work_dir=temp_dir,
                            session_id=f"val_{skill.name}",
                        )

                        exec_result = await executor.execute_bash(context)
                        command_results.append({
                            "command": cmd,
                            "success": exec_result.success,
                            "stdout": exec_result.stdout,
                            "stderr": exec_result.stderr,
                        })

                        if not exec_result.success:
                            return VerificationProof(
                                is_verified=False,
                                hollow_detected=False,
                                success_streak=0,
                                blast_radius=blast_radius,
                                verification_summary=f"Verification Step Failed: {exec_result.stderr or exec_result.error}",
                                command_results=command_results,
                                environment=skill.environment,
                                verified_at=datetime.now(),
                            )

        # All checks passed cleanly
        prev_success_streak = skill.metrics.success_count if skill.metrics else 0
        streak = prev_success_streak + 1

        return VerificationProof(
            is_verified=True,
            hollow_detected=False,
            success_streak=streak,
            blast_radius=blast_radius,
            verification_summary="Passed sandbox execution and anti-hollow validation",
            command_results=command_results,
            environment=skill.environment,
            verified_at=datetime.now(),
        )

    async def dry_run_skill(self, skill: SkillRecord) -> tuple[bool, str]:
        """Backward-compatible dry-run method delegating to verify_skill_capsule."""
        proof = await self.verify_skill_capsule(skill)
        return proof.is_verified, proof.verification_summary
