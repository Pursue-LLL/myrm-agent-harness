"""Hollow test detector for skill verification.

Detects trivial assertions, dummy prints, and vacuous verification scripts to prevent fake passes in skill evolution.

[INPUT]
- (none)

[OUTPUT]
- HollowTestResult: Detection result structure.
- HollowTestDetector: AST and semantic validator against hollow tests.

[POS]
Hollow test detection engine. Validates that skill verification steps and tests contain genuine, non-trivial assertions and produce meaningful execution side-effects.
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["HollowTestDetector", "HollowTestResult"]


@dataclass
class HollowTestResult:
    """Result of hollow test detection."""

    is_hollow: bool = False
    reasons: list[str] = field(default_factory=list)
    has_assert: bool = False
    non_trivial_assert_count: int = 0
    details: dict[str, Any] = field(default_factory=dict)


class HollowTestDetector:
    """Detects hollow/trivial tests and verification commands."""

    # Shell commands that are purely printing or trivial exits without state change
    _TRIVIAL_SHELL_PATTERNS = [
        re.compile(r"^\s*echo(\s+.*)?$", re.IGNORECASE),
        re.compile(r"^\s*printf(\s+.*)?$", re.IGNORECASE),
        re.compile(r"^\s*(true|exit\s+0|:|pass)\s*$", re.IGNORECASE),
        re.compile(r"^\s*console\.log\(.*\)\s*;?\s*$", re.IGNORECASE),
    ]

    def analyze_python_code(self, code: str) -> HollowTestResult:
        """Analyze Python test/validation code for hollow patterns via AST."""
        if not code.strip():
            return HollowTestResult(
                is_hollow=True,
                reasons=["Empty code provided"],
                has_assert=False,
                non_trivial_assert_count=0,
            )

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return HollowTestResult(
                is_hollow=True,
                reasons=[f"SyntaxError in test code: {e.msg}"],
                has_assert=False,
                non_trivial_assert_count=0,
            )

        assert_nodes: list[ast.Assert] = []
        call_nodes: list[ast.Call] = []
        stmt_count = 0

        for node in ast.walk(tree):
            if isinstance(node, ast.stmt):
                stmt_count += 1
            if isinstance(node, ast.Assert):
                assert_nodes.append(node)
            elif isinstance(node, ast.Call):
                call_nodes.append(node)

        reasons: list[str] = []
        non_trivial_asserts = 0

        if not assert_nodes:
            # Check if there are testing framework calls (like pytest.raises or unittest assertions)
            framework_asserts = self._find_framework_assertions(call_nodes)
            if framework_asserts == 0 and not self._has_custom_verification_logic(tree):
                reasons.append("No assertion statements (`assert`) or test framework checks found")
            else:
                non_trivial_asserts += framework_asserts
        else:
            for node in assert_nodes:
                is_trivial, trivial_reason = self._is_trivial_assert(node)
                if is_trivial:
                    reasons.append(f"Trivial assertion detected: {trivial_reason}")
                else:
                    non_trivial_asserts += 1

        is_hollow = (non_trivial_asserts == 0) and bool(reasons)

        return HollowTestResult(
            is_hollow=is_hollow,
            reasons=reasons,
            has_assert=len(assert_nodes) > 0,
            non_trivial_assert_count=non_trivial_asserts,
            details={
                "total_statements": stmt_count,
                "total_asserts": len(assert_nodes),
                "non_trivial_asserts": non_trivial_asserts,
            },
        )

    def analyze_shell_command(self, command: str) -> HollowTestResult:
        """Analyze a verification shell command for trivial/dummy execution."""
        clean_cmd = command.strip()
        if not clean_cmd:
            return HollowTestResult(
                is_hollow=True,
                reasons=["Empty command string"],
                has_assert=False,
                non_trivial_assert_count=0,
            )

        for pattern in self._TRIVIAL_SHELL_PATTERNS:
            if pattern.match(clean_cmd):
                return HollowTestResult(
                    is_hollow=True,
                    reasons=[f"Command `{clean_cmd}` is a trivial echo/noop without assertions or verification"],
                    has_assert=False,
                    non_trivial_assert_count=0,
                    details={"matched_pattern": pattern.pattern},
                )

        return HollowTestResult(
            is_hollow=False,
            reasons=[],
            has_assert=True,
            non_trivial_assert_count=1,
            details={"command": clean_cmd},
        )

    def _is_trivial_assert(self, node: ast.Assert) -> tuple[bool, str]:
        """Determine whether an AST Assert node is trivially true or useless."""
        test = node.test

        # assert True / assert False
        if isinstance(test, ast.Constant):
            return True, f"constant literal `{test.value}`"

        # assert 1 == 1 / assert "a" == "a"
        if isinstance(test, ast.Compare):
            if isinstance(test.left, ast.Constant) and len(test.comparators) == 1 and isinstance(test.comparators[0], ast.Constant):
                if test.left.value == test.comparators[0].value:
                    return True, f"identical constant comparison `{test.left.value} == {test.comparators[0].value}`"

        # assert not False / assert not None
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            if isinstance(test.operand, ast.Constant):
                return True, f"`not` on constant `{test.operand.value}`"

        return False, ""

    def _find_framework_assertions(self, call_nodes: list[ast.Call]) -> int:
        """Detect calls to unittest (assertEqual, assertTrue) or pytest assertions."""
        count = 0
        for call in call_nodes:
            if isinstance(call.func, ast.Attribute):
                attr_name = call.func.attr
                if attr_name.startswith("assert") or attr_name in ("raises", "approx", "fail"):
                    count += 1
            elif isinstance(call.func, ast.Name):
                func_name = call.func.id
                if func_name.startswith("assert_") or func_name == "pytest":
                    count += 1
        return count

    def _has_custom_verification_logic(self, tree: ast.AST) -> bool:
        """Check if code has custom validation e.g., if error: raise Exception."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise):
                return True
        return False
