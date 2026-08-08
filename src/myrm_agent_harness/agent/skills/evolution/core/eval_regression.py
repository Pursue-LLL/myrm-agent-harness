"""EvalCase regression gate for skill evolution.

[INPUT]
- agent.skills.evolution.core.types::SkillRecord (POS: Data types for skill evolution system.)

[OUTPUT]
- filter_variants_by_regression: Non-blocking regression gate that applies score penalties.

[POS]
Non-blocking regression gate for the skill evolution pipeline. Runs bound
EvalCases against candidate variants BEFORE LLM evaluation, applying score
penalties rather than hard-blocking to account for potentially inaccurate
auto-generated EvalCases.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import re
from typing import Any

from .types import SkillRecord

__all__ = ["filter_variants_by_regression"]

_REGRESSION_TIMEOUT_S = 5.0
_HARD_FAIL_THRESHOLD = 1.0
_PENALTY_PER_FAILED_CASE = 0.15


async def filter_variants_by_regression(
    skill: SkillRecord,
    variants: list[str],
    logger: logging.Logger,
) -> tuple[list[str], dict[str, float]]:
    """Run EvalCase regression against each variant, return survivors and penalties.

    Strategy (non-blocking):
    - If the skill has no eval_cases, skip with zero penalties.
    - For each variant, run lightweight assertion checks.
    - Compute a penalty score proportional to failed cases.
    - Only hard-filter variants that fail ALL cases (100% regression).
    - Return surviving variants and their penalty map.
    """
    if not skill.eval_cases:
        return variants, {}

    penalties: dict[str, float] = {}
    surviving: list[str] = []

    for variant in variants:
        penalty = await _compute_regression_penalty(skill, variant, logger)
        penalties[variant] = penalty
        if penalty < _HARD_FAIL_THRESHOLD:
            surviving.append(variant)
        else:
            logger.info(
                "Variant hard-filtered: 100%% EvalCase regression for skill '%s'",
                skill.name,
            )

    return surviving, penalties


async def _compute_regression_penalty(
    skill: SkillRecord,
    variant_code: str,
    logger: logging.Logger,
) -> float:
    """Compute penalty for a single variant based on EvalCase assertions."""
    cases = skill.eval_cases
    if not cases:
        return 0.0

    total = len(cases)
    failed = 0

    for case_dict in cases:
        try:
            passed = await asyncio.wait_for(
                _run_single_case(case_dict, variant_code),
                timeout=_REGRESSION_TIMEOUT_S,
            )
            if not passed:
                failed += 1
        except TimeoutError:
            logger.debug("EvalCase timed out for skill '%s', treating as pass", skill.name)
        except Exception:
            logger.debug("EvalCase error for skill '%s', treating as pass", skill.name, exc_info=True)

    if total == 0:
        return 0.0

    return min(failed * _PENALTY_PER_FAILED_CASE, _HARD_FAIL_THRESHOLD)


async def _run_single_case(case_dict: dict[str, Any], variant_code: str) -> bool:
    """Run assertions from a single EvalCase dict against the variant code.

    Supported assertion types (lightweight, no agent execution):
    - sandbox_assertions with type "code_contains" / "code_not_contains":
      Check that variant code contains/excludes specific patterns.
    - sandbox_assertions with type "ast_valid":
      Verify the variant code is valid Python AST.
    - sandbox_assertions with type "imports_module":
      Check that the variant imports a specific module.
    """
    assertions = case_dict.get("sandbox_assertions", [])
    if not assertions:
        expected_tools = case_dict.get("expected_tools", [])
        if expected_tools:
            return _check_tool_mentions(variant_code, expected_tools)
        return True

    for assertion in assertions:
        a_type = assertion.get("type", "")
        target = assertion.get("target", "")

        if a_type == "code_contains":
            if target not in variant_code:
                return False
        elif a_type == "code_not_contains":
            if target in variant_code:
                return False
        elif a_type == "ast_valid":
            try:
                ast.parse(variant_code)
            except SyntaxError:
                return False
        elif a_type == "imports_module":
            if not _check_imports(variant_code, target):
                return False
        elif a_type == "regex_match":
            try:
                if not re.search(target, variant_code):
                    return False
            except re.error:
                return False

    return True


def _check_tool_mentions(code: str, expected_tools: list[str | dict[str, Any]]) -> bool:
    """Check that variant code mentions expected tool names."""
    for tool in expected_tools:
        tool_name = tool if isinstance(tool, str) else tool.get("name", "")
        if tool_name and tool_name not in code:
            return False
    return True


def _check_imports(code: str, module_name: str) -> bool:
    """Check if code imports a specific module."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module_name or alias.name.startswith(f"{module_name}."):
                    return True
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (node.module == module_name or node.module.startswith(f"{module_name}."))
        ):
            return True
    return False
