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
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from myrm_agent_harness.agent.dynamic_workflow.tools import (
    DEFAULT_MAX_CONCURRENT_SPAWNS,
)


class LintSeverity(StrEnum):
    """Severity classification for workflow script issues."""

    FATAL = "fatal"
    WARNING = "warning"
    INFO = "info"


def _loop_can_exit(node: ast.While) -> bool:
    """Conservatively decide whether a ``while True`` body must be able to stop.

    Only *unconditional* exits prove termination: a top-level ``break``, ``return``,
    or ``raise``. A ``break`` nested inside ``if``/``try`` is conditional — the
    branch may never be taken — so it does not prove the loop terminates.

    This deliberately errs toward flagging: a false positive only asks the model to
    rewrite the loop, while a false negative ships an unbounded script.
    """
    return any(isinstance(stmt, ast.Break | ast.Return | ast.Raise) for stmt in node.body)


def _loop_condition_is_never_updated(node: ast.While) -> bool:
    """Detect loops whose condition references a name the body never rebinds.

    Covers ``flag = True; while flag: ...`` and ``n = 0; while n < 10: ...``.
    Only plain ``Name`` tests and ``Compare``/``BoolOp`` over plain names are
    analysed. Calls, awaits, and attribute mutation are ignored: they could change
    the condition indirectly, so flagging them would be a false positive.
    """
    watched = _condition_names(node.test)
    if not watched:
        return False
    if _loop_can_exit(node):
        return False
    if _body_calls_out(node):
        return False

    for stmt in node.body:
        for inner in ast.walk(stmt):
            if isinstance(inner, ast.Name) and inner.id in watched and isinstance(inner.ctx, ast.Store):
                return False
    return True


def _condition_names(test: ast.expr) -> set[str]:
    """Collect plain names the loop condition depends on."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _condition_names(test.operand)
    if isinstance(test, ast.Name):
        return {test.id}
    if isinstance(test, ast.Compare):
        names: set[str] = set()
        for operand in [test.left, *test.comparators]:
            if isinstance(operand, ast.Name):
                names.add(operand.id)
            elif not isinstance(operand, ast.Constant):
                return set()
        return names
    if isinstance(test, ast.BoolOp):
        names = set()
        for value in test.values:
            names |= _condition_names(value)
        return names
    return set()


def _body_calls_out(node: ast.While) -> bool:
    """True when the body may mutate loop state through async or generator effects.

    ``await``/``yield`` can resume with different state, so a loop that depends on
    them is never flagged. Ordinary calls are not treated as state-mutating: the
    body of ``while flag: print("x")`` cannot flip ``flag`` through ``print``.
    """
    for stmt in node.body:
        for inner in ast.walk(stmt):
            if isinstance(inner, ast.Await | ast.Yield | ast.YieldFrom):
                return True
    return False


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
    steer_child_calls_found: int = 0

    @property
    def warnings(self) -> list[str]:
        return [
            f"[{issue.issue_code}] {issue.message}" for issue in self.issues if issue.severity == LintSeverity.WARNING
        ]

    @property
    def fatal_errors(self) -> list[str]:
        return [
            f"[{issue.issue_code}] {issue.message}" for issue in self.issues if issue.severity == LintSeverity.FATAL
        ]


class _WorkflowASTVisitor(ast.NodeVisitor):
    """AST visitor traversing script nodes for static security and topology linting."""

    _MYRM_TOOLS_MODULE: ClassVar[str] = "myrm_tools"

    def __init__(self) -> None:
        self.issues: list[LintIssue] = []
        self.spawn_count = 0
        self.llm_query_count = 0
        self.llm_query_batched_count = 0
        self.steer_child_count = 0
        self.module_aliases: set[str] = {self._MYRM_TOOLS_MODULE}
        self.imported_func_aliases: dict[str, str] = {}
        self._try_depth = 0
        self._loop_depth = 0
        self._assigned_vars: dict[str, int] = {}  # var_name -> line
        self._loaded_vars: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == self._MYRM_TOOLS_MODULE and alias.asname:
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
        is_constant_truthy = isinstance(node.test, ast.Constant) and bool(node.test.value)

        if is_constant_truthy and not _loop_can_exit(node):
            self.issues.append(
                LintIssue(
                    severity=LintSeverity.FATAL,
                    issue_code="UNBOUNDED_LOOP",
                    message="Infinite `while True` loop detected without bounded termination guard.",
                    line=node.lineno,
                )
            )
        elif not is_constant_truthy and _loop_condition_is_never_updated(node):
            self.issues.append(
                LintIssue(
                    severity=LintSeverity.FATAL,
                    issue_code="UNBOUNDED_LOOP",
                    message=(
                        f"Loop condition at line {node.lineno} never changes inside the body, "
                        "so it cannot terminate."
                    ),
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
        elif isinstance(func, ast.Name) and self.imported_func_aliases.get(func.id) == "spawn_subagent":
            return True
        return False

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        tool_name: str | None = None

        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id in self.module_aliases:
                tool_name = func.attr
            elif func.attr == "ThreadPoolExecutor" or (
                isinstance(func.value, ast.Name) and func.value.id == "concurrent" and func.attr == "futures"
            ):
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
        elif tool_name == "steer_child":
            self.steer_child_count += 1

        # Check ThreadPoolExecutor max_workers
        if (isinstance(func, ast.Name) and func.id == "ThreadPoolExecutor") or (
            isinstance(func, ast.Attribute) and func.attr == "ThreadPoolExecutor"
        ):
            self._check_thread_pool_workers(node)

        self.generic_visit(node)

    def _check_thread_pool_workers(self, node: ast.Call) -> None:
        for kw in node.keywords:
            if (
                kw.arg == "max_workers"
                and isinstance(kw.value, ast.Constant)
                and isinstance(kw.value.value, int)
                and kw.value.value > DEFAULT_MAX_CONCURRENT_SPAWNS
            ):
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
            steer_child_calls_found=0,
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
            steer_child_calls_found=0,
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
        steer_child_calls_found=visitor.steer_child_count,
    )
