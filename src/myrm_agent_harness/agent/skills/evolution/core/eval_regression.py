"""EvalCase regression gate for skill evolution.

[INPUT]
- agent.skills.evolution.core.types::SkillRecord (POS: Data types for skill evolution system.)

[OUTPUT]
- filter_variants_by_regression: Baseline-relative regression gate that applies score penalties.

[POS]
Regression gate for the skill evolution pipeline. Runs bound EvalCases against
candidate variants BEFORE LLM evaluation. Only the cases the ORIGINAL content
satisfies are guarded: a case the original already fails (for example a Python
AST check written against a Markdown SOP) cannot be regressed, so it is neither
penalised nor counted toward the hard filter. Variants lose score per guarded
case they drop and are removed only when they drop every guarded case, which
keeps the gate non-blocking for potentially inaccurate auto-generated EvalCases.
"""

from __future__ import annotations

import ast
import logging
import re
from typing import Any

from .types import SkillRecord

__all__ = ["filter_variants_by_regression"]

_PENALTY_PER_LOST_CASE = 0.15
_MAX_PENALTY = 1.0


async def filter_variants_by_regression(
    skill: SkillRecord,
    variants: list[str],
    logger: logging.Logger,
) -> tuple[list[str], dict[str, float]]:
    """Run EvalCase regression against each variant, return survivors and penalties.

    Strategy (non-blocking):
    - Guard only the eval_cases the original skill content passes; with none
      guarded (no eval_cases, or none the original satisfies) every variant survives
      with zero penalties.
    - Penalise each variant ``_PENALTY_PER_LOST_CASE`` per guarded case it fails.
    - Hard-filter variants that fail ALL guarded cases (100% regression).
    - Return surviving variants and their penalty map.
    """
    guarded = [case for case in skill.eval_cases or [] if _run_single_case(case, skill.content)]
    if not guarded:
        return variants, {}

    penalties: dict[str, float] = {}
    surviving: list[str] = []

    for variant in variants:
        lost = sum(1 for case in guarded if not _run_single_case(case, variant))
        penalties[variant] = min(lost * _PENALTY_PER_LOST_CASE, _MAX_PENALTY)
        if lost < len(guarded):
            surviving.append(variant)
        else:
            logger.info(
                "Variant hard-filtered: 100%% regression of guarded EvalCases for skill '%s'",
                skill.name,
            )

    return surviving, penalties


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
                if alias.name == module_name or alias.name.startswith(f"{module_name}."):
                    return True
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (node.module == module_name or node.module.startswith(f"{module_name}."))
        ):
            return True
    return False
