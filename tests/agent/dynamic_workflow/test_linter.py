"""Tests for Dynamic Workflow AST linter and false-edge dataflow detector."""

import pytest

from myrm_agent_harness.agent.dynamic_workflow.linter import (
    LintSeverity,
    lint_workflow_script,
)


def test_lint_clean_pipeline_script():
    script = """\
\"\"\"Research and audit payment gateways.\"\"\"
import myrm_tools
import json

def main():
    try:
        res1 = myrm_tools.spawn_subagent(
            task_id="step1",
            agent_type="generalPurpose",
            task_description="Search payment providers",
            readonly=True,
        )
    except Exception as e:
        res1 = {"success": False, "error": str(e)}

    try:
        res2 = myrm_tools.spawn_subagent(
            task_id="step2",
            agent_type="generalPurpose",
            task_description=f"Audit providers: {res1.get('result')}",
            readonly=True,
        )
    except Exception as e:
        res2 = {"success": False, "error": str(e)}

    print(json.dumps({"stage1": res1, "stage2": res2}))

main()
"""
    report = lint_workflow_script(script, query="Audit payment gateways")
    assert report.is_valid is True
    assert report.spawn_calls_found == 2
    assert report.goal_brief == "Research and audit payment gateways."
    assert len(report.warnings) == 0
    assert len(report.fatal_errors) == 0


def test_lint_syntax_error():
    broken_script = """\
import myrm_tools
def broken(
    return myrm_tools.spawn_subagent()
"""
    report = lint_workflow_script(broken_script)
    assert report.is_valid is False
    assert len(report.fatal_errors) >= 1
    assert any("SYNTAX_ERROR" in err for err in report.fatal_errors)


def test_lint_empty_script():
    report = lint_workflow_script("   \n\n  ")
    assert report.is_valid is False
    assert any("EMPTY_SCRIPT" in err for err in report.fatal_errors)


def test_lint_unbounded_while_loop():
    script = """\
import myrm_tools

while True:
    try:
        r = myrm_tools.spawn_subagent(task_id="t1", agent_type="generalPurpose", task_description="x")
        if r.get("success"):
            break
    except Exception:
        pass
"""
    report = lint_workflow_script(script)
    assert report.is_valid is False
    assert any("UNBOUNDED_LOOP" in err for err in report.fatal_errors)


def test_lint_uncaught_spawn():
    script = """\
import myrm_tools
res = myrm_tools.spawn_subagent(task_id="t1", agent_type="generalPurpose", task_description="x")
print(res)
"""
    report = lint_workflow_script(script)
    assert report.is_valid is True  # Warning, not Fatal
    assert any("UNCAUGHT_SPAWN" in warn for warn in report.warnings)


def test_lint_dead_output_false_edge():
    script = """\
import myrm_tools
import json

try:
    used_res = myrm_tools.spawn_subagent(task_id="t1", agent_type="generalPurpose", task_description="x")
except Exception as e:
    used_res = {"error": str(e)}

try:
    dead_res = myrm_tools.spawn_subagent(task_id="t2", agent_type="generalPurpose", task_description="y")
except Exception as e:
    dead_res = {"error": str(e)}

print(json.dumps({"result": used_res}))
"""
    report = lint_workflow_script(script)
    assert report.is_valid is True
    assert any("DEAD_OUTPUT" in warn and "dead_res" in warn for warn in report.warnings)
    # used_res was read, so no dead_output for used_res
    assert not any("DEAD_OUTPUT" in warn and "used_res" in warn for warn in report.warnings)


def test_lint_aliased_import():
    script = """\
from myrm_tools import spawn_subagent as spawn, llm_query as direct_llm
import json

try:
    r = spawn(task_id="sub", agent_type="generalPurpose", task_description="work")
except Exception as e:
    r = {"error": str(e)}

q = direct_llm(prompt="summary")
print(json.dumps({"sub": r, "q": q}))
"""
    report = lint_workflow_script(script)
    assert report.is_valid is True
    assert report.spawn_calls_found == 1
    assert report.llm_query_calls_found == 1
    assert len(report.warnings) == 0


def test_lint_excessive_workers():
    script = """\
from concurrent.futures import ThreadPoolExecutor
import myrm_tools

with ThreadPoolExecutor(max_workers=16) as executor:
    pass
"""
    report = lint_workflow_script(script)
    assert report.is_valid is True
    assert any("EXCESSIVE_WORKERS" in warn for warn in report.warnings)


def test_lint_steer_child_call():
    script = """\
import myrm_tools
import json

try:
    r = myrm_tools.spawn_subagent(task_id="t1", agent_type="generalPurpose", task_description="x")
except Exception as e:
    r = {"error": str(e)}

steer_res = myrm_tools.steer_child(task_id="t1", message="Please refine findings")
print(json.dumps({"sub": r, "steer": steer_res}))
"""
    report = lint_workflow_script(script)
    assert report.is_valid is True
    assert report.spawn_calls_found == 1
    assert report.steer_child_calls_found == 1
    assert len(report.warnings) == 0

