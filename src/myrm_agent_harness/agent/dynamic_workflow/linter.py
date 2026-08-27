"""Dynamic Workflow AST static analysis and dataflow false-edge linter.

[INPUT]
- dynamic_workflow.tools::DEFAULT_MAX_CONCURRENT_SPAWNS (POS: Per-workflow concurrency cap)

[OUTPUT]
- WorkflowLintReport: Comprehensive lint result with severity, issues, and counts
- lint_workflow_script: Core entry point for static validation

[POS]
Compiles and statically inspects dynamic workflow scripts before PTC sandbox execution.
Detects syntax errors, unbounded loops, uncaught spawn exceptions, and dataflow false edges
(subagent outputs assigned but never consumed downstream).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar

from myrm_agent_harness.agent.dynamic_workflow.tools import (
    DEFAULT_MAX_CONCURRENT_SPAWNS,
)


class LintSeverity(str, Enum):
    """Severity classification for workflow script issues."""

    FATAL = "fatal"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class LintIssue:
    """Individual lint issue discovered in the workflow script."""

    severity: LintSeverity
    issue_code: str
    message: str
    line: int | None = None


@dataclass(frozen=True, slots=True)
class WorkflowLintReport:
    """Consolidated static analysis report for an orchestration script."""

    is_valid: bool
    issues: tuple[LintIssue, ...]
    spawn_calls_found: int
    llm_query_calls_found: int
    llm_query_batched_calls_found: int
    goal_brief: str
    summary: str

    @property
    def warnings(self) -> list[str]:
        return [f"[{issue.issue_code}] {issue.message}" for issue in self.issues if issue.severity == LintSeverity.WARNING]

    @property
    def fatal_errors(self) -> list[str]:
        return [f"[{issue.issue_code}] {issue.message}" for issue in self.issues if issue.severity == LintSeverity.FATAL]


class _WorkflowASTVisitor(ast.NodeVisitor):
    """AST visitor traversing script nodes for static security and topology linting."""

    _MYRM_TOOLS_MODULE: ClassVar[str] = "myrm_tools"

    def __init__(self) -> None:
        self.issues: list[LintIssue] = []
        self.spawn_count = 0
        self.llm_query_count = 0
        self.llm_query_batched_count = 0
        self.module_aliases: set[str] = {self._MYRM_TOOLS_MODULE}
        self.imported_func_aliases: dict[str, str] = {}
        self._try_depth = 0
        self._loop_depth = 0
        self._assigned_vars: dict[str, int] = {}  # var_name -> line
        self._loaded_vars: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == self._MYRM_TOOLS_MODULE:
                if alias.asname:
                    self.module_aliases.add(alias.asname)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == self._MYRM_TOOLS_MODULE:
            for alias in node.names:
                target_name = alias.asname or alias.name
                self.imported_func_aliases[target_name] = alias.name
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._try_depth += 1
        for stmt in node.body:
            self.visit(stmt)
        self._try_depth -= 1
        for handler in node.handlers:
            self.visit(handler)
        for stmt in node.orelse:
            self.visit(stmt)
        for stmt in node.finalbody:
            self.visit(stmt)

    def visit_While(self, node: ast.While) -> None:
        self._loop_depth += 1
        # Check for while True / while 1 unbounded loop
        is_constant_truthy = False
        if isinstance(node.test, ast.Constant) and bool(node.test.value):
            is_constant_truthy = True
        elif isinstance(node.test, ast.NameConstant) and node.test.value is True:  # type: ignore[attr-defined]
            is_constant_truthy = True

        if is_constant_truthy:
            self.issues.append(
                LintIssue(
                    severity=LintSeverity.FATAL,
                    issue_code="UNBOUNDED_LOOP",
                    message="Infinite `while True` loop detected without bounded termination guard.",
                    line=node.lineno,
                )
            )
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_For(self, node: ast.For) -> None:
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_Assign(self, node: ast.Assign) -> None:
        # Check if the right-hand side is a spawn call
        is_spawn = self._is_spawn_call(node.value)
        if is_spawn:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._assigned_vars[target.id] = node.lineno
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._loaded_vars.add(node.id)
        self.generic_visit(node)

    def _is_spawn_call(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id in self.module_aliases and func.attr == "spawn_subagent":
                return True
        elif isinstance(func, ast.Name):
            if self.imported_func_aliases.get(func.id) == "spawn_subagent":
                return True
        return False

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        tool_name: str | None = None

        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id in self.module_aliases:
                tool_name = func.attr
            elif func.attr == "ThreadPoolExecutor" or (isinstance(func.value, ast.Name) and func.value.id == "concurrent" and func.attr == "futures"):
                pass
        elif isinstance(func, ast.Name):
            tool_name = self.imported_func_aliases.get(func.id)

        if tool_name == "spawn_subagent":
            self.spawn_count += 1
            if self._try_depth == 0:
                self.issues.append(
                    LintIssue(
                        severity=LintSeverity.WARNING,
                        issue_code="UNCAUGHT_SPAWN",
                        message="`spawn_subagent` call is not enclosed in a try/except block; failure may abort the entire workflow.",
                        line=node.lineno,
                    )
                )
        elif tool_name == "llm_query":
            self.llm_query_count += 1
        elif tool_name == "llm_query_batched":
            self.llm_query_batched_count += 1

        # Check ThreadPoolExecutor max_workers
        if isinstance(func, ast.Name) and func.id == "ThreadPoolExecutor":
            self._check_thread_pool_workers(node)
        elif isinstance(func, ast.Attribute) and func.attr == "ThreadPoolExecutor":
            self._check_thread_pool_workers(node)

        self.generic_visit(node)

    def _check_thread_pool_workers(self, node: ast.Call) -> None:
        for kw in node.keywords:
            if kw.arg == "max_workers" and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, int) and kw.value.value > DEFAULT_MAX_CONCURRENT_SPAWNS:
                    self.issues.append(
                        LintIssue(
                            severity=LintSeverity.WARNING,
                            issue_code="EXCESSIVE_WORKERS",
                            message=(
                                f"`ThreadPoolExecutor` configured with max_workers={kw.value.value}, "
                                f"which exceeds recommended cap ({DEFAULT_MAX_CONCURRENT_SPAWNS})."
                            ),
                            line=node.lineno,
                        )
                    )

    def finalize_dataflow_checks(self) -> None:
        """Verify that assigned subagent output variables are referenced downstream."""
        for var_name, lineno in self._assigned_vars.items():
            if var_name not in self._loaded_vars:
                self.issues.append(
                    LintIssue(
                        severity=LintSeverity.WARNING,
                        issue_code="DEAD_OUTPUT",
                        message=f"Subagent output variable `{var_name}` is assigned at line {lineno} but never read or summarized.",
                        line=lineno,
                    )
                )


def lint_workflow_script(script_code: str, query: str = "") -> WorkflowLintReport:
    """Parse and lint a dynamic workflow Python script using standard library AST.

    Guarantees < 2ms execution with zero external dependencies.
    """
    cleaned_code = script_code.strip()
    if not cleaned_code:
        return WorkflowLintReport(
            is_valid=False,
            issues=(
                LintIssue(
                    severity=LintSeverity.FATAL,
                    issue_code="EMPTY_SCRIPT",
                    message="Orchestration script is empty.",
                ),
            ),
            spawn_calls_found=0,
            llm_query_calls_found=0,
            llm_query_batched_calls_found=0,
            goal_brief=query[:120] if query else "Empty workflow",
            summary="Static lint failed: Script is empty.",
        )

    try:
        tree = ast.parse(cleaned_code)
    except SyntaxError as exc:
        fatal_issue = LintIssue(
            severity=LintSeverity.FATAL,
            issue_code="SYNTAX_ERROR",
            message=f"Python syntax error at line {exc.lineno}, col {exc.offset}: {exc.msg}",
            line=exc.lineno,
        )
        return WorkflowLintReport(
            is_valid=False,
            issues=(fatal_issue,),
            spawn_calls_found=0,
            llm_query_calls_found=0,
            llm_query_batched_calls_found=0,
            goal_brief=query[:120] if query else "Invalid workflow",
            summary=f"Static lint failed: {fatal_issue.message}",
        )

    visitor = _WorkflowASTVisitor()
    visitor.visit(tree)
    visitor.finalize_dataflow_checks()

    # Derive goal brief from docstring or query
    docstring = ast.get_docstring(tree)
    if docstring:
        goal_brief = docstring.strip().split("\n")[0][:150]
    elif query:
        goal_brief = query.strip()[:150]
    else:
        goal_brief = f"Dynamic Workflow with {visitor.spawn_count} sub-agent(s)"

    has_fatal = any(issue.severity == LintSeverity.FATAL for issue in visitor.issues)
    is_valid = not has_fatal

    if not is_valid:
        fatal_msgs = "; ".join(issue.message for issue in visitor.issues if issue.severity == LintSeverity.FATAL)
        summary = f"Static lint failed: {fatal_msgs}"
    elif visitor.issues:
        warn_count = sum(1 for issue in visitor.issues if issue.severity == LintSeverity.WARNING)
        summary = f"Static lint passed with {warn_count} warning(s)."
    else:
        summary = "Static lint passed: Clean AST topology and dataflow."

    return WorkflowLintReport(
        is_valid=is_valid,
        issues=tuple(visitor.issues),
        spawn_calls_found=visitor.spawn_count,
        llm_query_calls_found=visitor.llm_query_count,
        llm_query_batched_calls_found=visitor.llm_query_batched_count,
        goal_brief=goal_brief,
        summary=summary,
    )
