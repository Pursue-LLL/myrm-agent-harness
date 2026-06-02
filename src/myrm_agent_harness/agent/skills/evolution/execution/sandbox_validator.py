"""Sandbox validation for evolved skills.

[INPUT]
- agent.skills.evolution.core.types::SkillRecord (POS: Data types for skill evolution system.)
- toolkits.code_execution.executors.test_executor::SubprocessCodeExecutor (POS: Run generated evolution tests in an isolated subprocess.)
- toolkits.code_execution.executors.local.executor::LocalExecutor (POS: Local code executor with persistent Bash sessions.)
- toolkits.code_execution.config::ExecutionConfig (POS: Code execution configuration layer.)

[OUTPUT]
- SandboxValidator: Validates skills in a subprocess dry-run with AST static analysis.
- test_syntax: function — test_syntax

[POS]
Sandbox validation for evolved skills. Uses AST analysis and the framework's native execution engine.
"""

import logging
import re
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


from myrm_agent_harness.agent.skills.evolution.core.types import SkillRecord
from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.base import ExecutionContext
from myrm_agent_harness.toolkits.code_execution.executors.local.executor import (
    LocalExecutor,
)
from myrm_agent_harness.toolkits.code_execution.executors.test_executor import (
    SubprocessCodeExecutor,
)

logger = logging.getLogger(__name__)


class SandboxValidator:
    """Validates skills in a subprocess dry-run with strict security constraints.

    Uses the framework's unified Execution Engine with PEP 578 Audit Hooks
    and shell command analysis.
    """

    def __init__(self, timeout_seconds: float = 10.0):
        self._test_executor = SubprocessCodeExecutor(
            timeout_seconds=timeout_seconds, allow_network=False
        )
        self._timeout_seconds = timeout_seconds

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
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("eval", "exec")
            ):
                return (
                    False,
                    f"HighRiskOperation: Use of '{node.func.id}' is strictly prohibited.\n```python\n{node.func.id}(...)\n```",
                )

        return True, "AST analysis passed"

    async def dry_run_skill(self, skill: SkillRecord) -> tuple[bool, str]:
        """Run syntax checks, AST analysis, and secure verification steps for the skill."""
        # 1. Syntax Check (Python blocks)
        python_blocks = re.findall(r"```python\n(.*?)\n```", skill.content, re.DOTALL)
        if python_blocks:
            combined_code = "\n\n".join(python_blocks)

            # 1.5 0-cost AST Static Analysis (Replaces LLM Fuzzing)
            ast_passed, ast_msg = self._run_ast_analysis(combined_code)
            if not ast_passed:
                logger.warning(
                    f"AST Static Analysis failed for {skill.name}: {ast_msg}"
                )
                return False, ast_msg

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
            if not result.passed:
                logger.warning(
                    f"Dry-run syntax check failed for {skill.name}:\n{result.stdout}\n{result.stderr}"
                )
                return False, f"Syntax Check Failed: {result.stderr or result.stdout}"

        # 2. Execute Verification Steps (if any) securely using framework engine
        if skill.verification_steps:
            # Initialize a secure LocalExecutor for verification steps
            config = ExecutionConfig()
            config.local.max_execution_time = int(self._timeout_seconds)
            config.network.allow_network = False

            with tempfile.TemporaryDirectory() as temp_dir:
                # We use contextlib.AsyncExitStack to properly manage the async context manager
                async with LocalExecutor(config, temp_dir) as executor:
                    for step in skill.verification_steps:
                        cmd = step.get("command")
                        if not cmd:
                            continue

                        # 2.5 Block inline script execution bypasses
                        if re.search(r"(python|python3|node)\s+-c\s+[\"']", cmd):
                            return False, f"HighRiskOperation: Inline script execution via bash (`python -c`) is strictly prohibited to prevent AST bypasses.\n```bash\n{cmd}\n```"

                        # Execute via the framework's 5-layer validated Bash execution
                        context = ExecutionContext(
                            code=cmd,
                            timeout=int(self._timeout_seconds),
                            allow_network=False,
                            workspace_root=temp_dir,
                            work_dir=temp_dir,
                            session_id=f"val_{skill.name}",
                        )

                        exec_result = await executor.execute_bash(context)

                        if not exec_result.success:
                            logger.warning(
                                f"Skill {skill.name} verification step failed or rejected: {cmd}\n{exec_result.stderr}\n{exec_result.error}"
                            )
                            return False, f"Verification Step Failed: {exec_result.stderr or exec_result.error}"

        logger.info(f"Dry-run sandbox passed securely for {skill.name}")
        return True, "Passed"
