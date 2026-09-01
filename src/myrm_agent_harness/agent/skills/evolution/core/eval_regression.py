"""EvalCase regression gate for skill evolution.

[INPUT]
- agent.skills.evolution.core.types::SkillRecord (POS: Data types for skill evolution system.)

[OUTPUT]
- filter_variants_by_regression: Non-blocking regression gate that applies score penalties.
- evaluate_content_assertions: Public static-assertion pass-rate evaluator for arbitrary skill content.

[POS]
Non-blocking regression gate for the skill evolution pipeline. Runs bound
EvalCases against candidate variants BEFORE LLM evaluation, applying score
penalties rather than hard-blocking to account for potentially inaccurate
auto-generated EvalCases.
"""

from __future__ import annotations

import ast
import logging
import re
from typing import Any

from .types import SkillRecord

__all__ = ["evaluate_content_assertions", "filter_variants_by_regression"]

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
        pass_rate = evaluate_content_assertions(skill.eval_cases, variant)
        failed = len(skill.eval_cases) - round(pass_rate * len(skill.eval_cases))
        penalty = min(failed * _PENALTY_PER_FAILED_CASE, _HARD_FAIL_THRESHOLD)
        penalties[variant] = penalty
        if penalty < _HARD_FAIL_THRESHOLD:
            surviving.append(variant)
        else:
            logger.info(
                "Variant hard-filtered: 100%% EvalCase regression for skill '%s'",
                skill.name,
            )

    return surviving, penalties


def evaluate_content_assertions(
    eval_cases: list[dict[str, Any]],
    content: str,
) -> float:
    """Evaluate the static-assertion pass rate of skill content against bound EvalCases.

    Deterministic, zero-LLM, zero-network: regex/AST checks only, mirroring the
    regression gate's assertion semantics. Used both by the evolution pipeline
    (variant gating) and the change-manifest prediction/attribution loop.

    Returns the fraction of cases whose assertions all pass; returns 1.0 when
    there are no eval_cases (caller decides whether that means "no data").
    """
    if not eval_cases:
        return 1.0

    total = len(eval_cases)
    failed = sum(
        1 for case_dict in eval_cases if not _run_single_case(case_dict, content)
    )
    return (total - failed) / total


def _run_single_case(case_dict: dict[str, Any], variant_code: str) -> bool:
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
                if alias.name == module_name or alias.name.startswith(
                    f"{module_name}."
                ):
                    return True
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (
                node.module == module_name or node.module.startswith(f"{module_name}.")
            )
        ):
            return True
    return False
