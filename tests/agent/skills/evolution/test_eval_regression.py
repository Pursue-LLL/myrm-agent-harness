"""Tests for EvalCase regression gate and builder utilities."""

import logging

import pytest

from myrm_agent_harness.agent.skills.evolution.core.eval_regression import (
    _check_imports,
    _check_tool_mentions,
    _run_single_case,
    filter_variants_by_regression,
)
from myrm_agent_harness.agent.skills.evolution.core.types import SkillRecord
from myrm_agent_harness.eval.builder import build_skill_eval_cases


def _make_skill(**kwargs) -> SkillRecord:
    defaults = {
        "skill_id": "test-skill",
        "name": "test-skill",
        "description": "A test skill",
        "content": "print('hello')",
        "path": "/tmp/test.md",
        "lineage": None,
    }
    defaults.update(kwargs)
    return SkillRecord(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# filter_variants_by_regression
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_eval_cases_passthrough():
    """When skill has no eval_cases, all variants survive with zero penalty."""
    skill = _make_skill()
    variants = ["variant_a", "variant_b"]
    surviving, penalties = await filter_variants_by_regression(
        skill,
        variants,
        logging.getLogger("test"),
    )
    assert surviving == variants
    assert penalties == {}


@pytest.mark.asyncio
async def test_code_contains_pass():
    """Variant containing required pattern passes assertion."""
    skill = _make_skill(
        eval_cases=[
            {
                "message": "deploy",
                "sandbox_assertions": [{"type": "code_contains", "target": "nginx"}],
            }
        ]
    )
    variants = ["install nginx server", "install apache server"]
    surviving, penalties = await filter_variants_by_regression(
        skill,
        variants,
        logging.getLogger("test"),
    )
    assert "install nginx server" in surviving
    assert penalties.get("install apache server", 0) > 0


@pytest.mark.asyncio
async def test_code_not_contains_pass():
    """Variant without forbidden pattern passes."""
    skill = _make_skill(
        eval_cases=[
            {
                "message": "safe deploy",
                "sandbox_assertions": [
                    {"type": "code_not_contains", "target": "rm -rf /"}
                ],
            }
        ]
    )
    good = "deploy safely"
    bad = "deploy with rm -rf /"
    surviving, penalties = await filter_variants_by_regression(
        skill,
        [good, bad],
        logging.getLogger("test"),
    )
    assert good in surviving
    assert penalties.get(bad, 0) > 0


@pytest.mark.asyncio
async def test_ast_valid_pass():
    """Valid Python passes ast_valid assertion."""
    skill = _make_skill(
        eval_cases=[
            {
                "message": "run code",
                "sandbox_assertions": [{"type": "ast_valid", "target": ""}],
            }
        ]
    )
    good = "x = 1 + 2"
    bad = "x = 1 +"
    surviving, penalties = await filter_variants_by_regression(
        skill,
        [good, bad],
        logging.getLogger("test"),
    )
    assert good in surviving
    assert penalties.get(bad, 0) > 0


@pytest.mark.asyncio
async def test_imports_module_pass():
    """Variant that imports the required module passes."""
    skill = _make_skill(
        eval_cases=[
            {
                "message": "use json",
                "sandbox_assertions": [{"type": "imports_module", "target": "json"}],
            }
        ]
    )
    good = "import json\njson.dumps({})"
    bad = "x = 1"
    surviving, penalties = await filter_variants_by_regression(
        skill,
        [good, bad],
        logging.getLogger("test"),
    )
    assert good in surviving
    assert penalties.get(bad, 0) > 0


@pytest.mark.asyncio
async def test_regex_match_pass():
    """Variant matching regex passes."""
    skill = _make_skill(
        eval_cases=[
            {
                "message": "check pattern",
                "sandbox_assertions": [{"type": "regex_match", "target": r"def \w+\("}],
            }
        ]
    )
    good = "def hello():\n    pass"
    bad = "x = 1"
    surviving, penalties = await filter_variants_by_regression(
        skill,
        [good, bad],
        logging.getLogger("test"),
    )
    assert good in surviving
    assert penalties.get(bad, 0) > 0


@pytest.mark.asyncio
async def test_all_fail_hard_filter():
    """If ALL eval cases fail, penalty reaches hard threshold and variant is filtered."""
    skill = _make_skill(
        eval_cases=[
            {
                "message": "a",
                "sandbox_assertions": [
                    {"type": "code_contains", "target": "MUST_HAVE_THIS"}
                ],
            },
            {
                "message": "b",
                "sandbox_assertions": [
                    {"type": "code_contains", "target": "AND_THIS_TOO"}
                ],
            },
            {
                "message": "c",
                "sandbox_assertions": [
                    {"type": "code_contains", "target": "AND_ALSO_THIS"}
                ],
            },
            {
                "message": "d",
                "sandbox_assertions": [
                    {"type": "code_contains", "target": "PLUS_THIS"}
                ],
            },
            {
                "message": "e",
                "sandbox_assertions": [{"type": "code_contains", "target": "ONE_MORE"}],
            },
            {
                "message": "f",
                "sandbox_assertions": [{"type": "code_contains", "target": "LAST_ONE"}],
            },
            {
                "message": "g",
                "sandbox_assertions": [{"type": "code_contains", "target": "FINAL"}],
            },
        ]
    )
    variants = ["nothing matches"]
    surviving, penalties = await filter_variants_by_regression(
        skill,
        variants,
        logging.getLogger("test"),
    )
    assert surviving == []
    assert penalties["nothing matches"] >= 1.0


@pytest.mark.asyncio
async def test_no_assertions_fallback_to_expected_tools():
    """When no sandbox_assertions, fall back to checking expected_tools mentions."""
    skill = _make_skill(
        eval_cases=[
            {
                "message": "use bash",
                "expected_tools": ["bash", "python"],
            }
        ]
    )
    good = "use bash and python to solve"
    bad = "use curl only"
    surviving, penalties = await filter_variants_by_regression(
        skill,
        [good, bad],
        logging.getLogger("test"),
    )
    assert good in surviving
    assert penalties.get(bad, 0) > 0


# --------------------------------------------------------------------------
# _run_single_case
# --------------------------------------------------------------------------


def test_run_single_case_empty_assertions():
    """Case with no assertions and no expected_tools always passes."""
    result = _run_single_case({"message": "test"}, "any code")
    assert result is True


# --------------------------------------------------------------------------
# _check_imports
# --------------------------------------------------------------------------


def test_check_imports_found():
    assert _check_imports("import os\nimport json", "json") is True


def test_check_imports_from_import():
    assert _check_imports("from pathlib import Path", "pathlib") is True


def test_check_imports_not_found():
    assert _check_imports("import os", "json") is False


def test_check_imports_syntax_error():
    assert _check_imports("x = 1 +", "json") is False


# --------------------------------------------------------------------------
# _check_tool_mentions
# --------------------------------------------------------------------------


def test_check_tool_mentions_all_present():
    assert _check_tool_mentions("use bash and python", ["bash", "python"]) is True


def test_check_tool_mentions_missing():
    assert _check_tool_mentions("use bash", ["bash", "python"]) is False


def test_check_tool_mentions_dict_format():
    assert _check_tool_mentions("use bash", [{"name": "bash"}]) is True


# --------------------------------------------------------------------------
# build_skill_eval_cases
# --------------------------------------------------------------------------


def test_build_skill_eval_cases_basic():
    cases = build_skill_eval_cases(
        skill_content="import json\njson.dumps({})",
        skill_name="json-helper",
    )
    assert len(cases) == 1
    assert cases[0]["message"] == "Use skill: json-helper"
    assertions = cases[0]["sandbox_assertions"]
    assert any(a["type"] == "ast_valid" for a in assertions)


def test_build_skill_eval_cases_with_patterns():
    cases = build_skill_eval_cases(
        skill_content="import json",
        skill_name="test",
        trigger_message="parse data",
        required_patterns=["json"],
        forbidden_patterns=["eval("],
    )
    assertions = cases[0]["sandbox_assertions"]
    assert any(
        a["type"] == "code_contains" and a["target"] == "json" for a in assertions
    )
    assert any(
        a["type"] == "code_not_contains" and a["target"] == "eval(" for a in assertions
    )
    assert cases[0]["message"] == "parse data"


# --------------------------------------------------------------------------
# Edge cases & boundary scenarios
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_case_failure_penalty():
    """Variant failing one eval_case gets a non-zero penalty."""
    skill = _make_skill(
        eval_cases=[
            {"sandbox_assertions": [{"type": "code_contains", "target": "deploy"}]},
        ]
    )
    variant = "just random stuff"
    _surviving, penalties = await filter_variants_by_regression(
        skill,
        [variant],
        logging.getLogger("test"),
    )
    assert penalties[variant] > 0


@pytest.mark.asyncio
async def test_mixed_assertion_types():
    """Variant that passes some assertion types but fails others."""
    skill = _make_skill(
        eval_cases=[
            {
                "sandbox_assertions": [
                    {"type": "ast_valid"},
                    {"type": "code_contains", "target": "import os"},
                    {"type": "regex_match", "target": r"def \w+"},
                    {"type": "code_not_contains", "target": "eval("},
                ],
            },
        ]
    )
    variant = "import os\ndef hello():\n    pass"
    surviving, penalties = await filter_variants_by_regression(
        skill,
        [variant],
        logging.getLogger("test"),
    )
    assert variant in surviving
    assert penalties[variant] == 0.0


@pytest.mark.asyncio
async def test_mixed_assertion_partial_fail():
    """Variant passes ast_valid and regex but fails code_contains."""
    skill = _make_skill(
        eval_cases=[
            {
                "sandbox_assertions": [
                    {"type": "ast_valid"},
                    {"type": "code_contains", "target": "import numpy"},
                ],
            },
        ]
    )
    variant = "import os\ndef hello():\n    pass"
    _surviving, penalties = await filter_variants_by_regression(
        skill,
        [variant],
        logging.getLogger("test"),
    )
    assert penalties[variant] > 0


@pytest.mark.asyncio
async def test_empty_variant_code():
    """Empty variant code should fail code_contains but pass code_not_contains."""
    skill = _make_skill(
        eval_cases=[
            {"sandbox_assertions": [{"type": "code_contains", "target": "import"}]},
            {"sandbox_assertions": [{"type": "code_not_contains", "target": "danger"}]},
        ]
    )
    surviving, penalties = await filter_variants_by_regression(
        skill,
        [""],
        logging.getLogger("test"),
    )
    assert "" in surviving
    assert penalties[""] > 0


@pytest.mark.asyncio
async def test_many_eval_cases_performance():
    """100 eval_cases should complete quickly without hanging."""
    import time

    cases = [
        {"sandbox_assertions": [{"type": "code_contains", "target": f"pattern_{i}"}]}
        for i in range(100)
    ]
    skill = _make_skill(eval_cases=cases)
    start = time.monotonic()
    _surviving, penalties = await filter_variants_by_regression(
        skill,
        ["pattern_0 pattern_1"],
        logging.getLogger("test"),
    )
    elapsed = time.monotonic() - start
    assert elapsed < 5.0, f"100 eval_cases took {elapsed:.2f}s, should be <5s"
    assert penalties["pattern_0 pattern_1"] > 0


@pytest.mark.asyncio
async def test_unknown_assertion_type_passes():
    """Unknown assertion type should be silently ignored (pass)."""
    skill = _make_skill(
        eval_cases=[
            {"sandbox_assertions": [{"type": "unknown_future_type", "target": "x"}]},
        ]
    )
    surviving, penalties = await filter_variants_by_regression(
        skill,
        ["any code"],
        logging.getLogger("test"),
    )
    assert "any code" in surviving
    assert penalties["any code"] == 0.0


def test_regex_match_invalid_pattern():
    """Invalid regex pattern must not crash; the case fails (returns False)."""
    result = _run_single_case(
        {"sandbox_assertions": [{"type": "regex_match", "target": "[invalid("}]},
        "any code",
    )
    assert result is False


@pytest.mark.asyncio
async def test_code_contains_unicode():
    """Unicode patterns should work in code_contains/code_not_contains."""
    skill = _make_skill(
        eval_cases=[
            {
                "sandbox_assertions": [
                    {"type": "code_contains", "target": "安装"},
                    {"type": "code_not_contains", "target": "删除"},
                ]
            },
        ]
    )
    variant = "安装 nginx 服务器"
    surviving, penalties = await filter_variants_by_regression(
        skill,
        [variant],
        logging.getLogger("test"),
    )
    assert variant in surviving
    assert penalties[variant] == 0.0
