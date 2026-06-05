"""Smart Auto-Verify — 编辑后自动类型诊断反馈

当 Agent 未提供 verify_command 时，框架根据文件扩展名自动推断并执行
对应的 CLI linter（如 pyright/tsc/go vet），将诊断结果以软报告形式
附加到工具返回值中，Agent 可据此自主修复。

设计原则：
- 软报告：不回滚文件，仅附加诊断信息到返回值
- 容错：linter 不可用/超时/失败均静默跳过
- 增量过滤：仅报告与编辑行范围相关的 Error 级别诊断
- 会话级缓存：避免重复探测 linter 可用性

[INPUT]
- toolkits.code_execution.executors.base::CodeExecutor (POS: CLI command executor)

[OUTPUT]
- run_auto_verify: 主入口函数，执行自动诊断并返回格式化结果

[POS]
Smart Auto-Verify. Infers and runs CLI linters after file edits when Agent
does not provide explicit verify_command. Provides soft diagnostic feedback.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)

AUTO_VERIFY_TIMEOUT_SECONDS = 15
MAX_REPORTED_DIAGNOSTICS = 5


@dataclass(frozen=True)
class LinterConfig:
    """Single linter configuration."""

    command_template: str
    detect_cmd: str


LINTER_REGISTRY: dict[str, LinterConfig] = {
    ".py": LinterConfig(
        command_template="pyright --outputjson {path}",
        detect_cmd="pyright",
    ),
    ".ts": LinterConfig(
        command_template="tsc --noEmit --pretty false --skipLibCheck {path}",
        detect_cmd="tsc",
    ),
    ".tsx": LinterConfig(
        command_template="tsc --noEmit --pretty false --skipLibCheck {path}",
        detect_cmd="tsc",
    ),
    ".go": LinterConfig(
        command_template="go vet {path}",
        detect_cmd="go",
    ),
    ".rs": LinterConfig(
        command_template="cargo check --message-format=short 2>&1",
        detect_cmd="cargo",
    ),
}

_linter_availability_cache: dict[str, bool] = {}


def _reset_cache() -> None:
    """Reset linter availability cache (for testing)."""
    _linter_availability_cache.clear()


async def _check_linter_available(executor: CodeExecutor, detect_cmd: str) -> bool:
    """Check if a linter binary is available via `which`."""
    if detect_cmd in _linter_availability_cache:
        return _linter_availability_cache[detect_cmd]

    from myrm_agent_harness.toolkits.code_execution.executors.models import (
        ExecutionContext,
    )

    ctx = ExecutionContext(code=f"which {detect_cmd}", work_dir=".", timeout=5)
    try:
        result = await executor.execute_bash(ctx)
        available = result.success
    except Exception:
        available = False

    _linter_availability_cache[detect_cmd] = available
    if available:
        logger.debug("Auto-verify: linter '%s' is available", detect_cmd)
    else:
        logger.debug("Auto-verify: linter '%s' not found, skipping", detect_cmd)
    return available


@dataclass
class Diagnostic:
    """Parsed diagnostic entry."""

    file: str
    line: int
    col: int
    severity: str
    message: str


def _parse_pyright_output(raw: str) -> list[Diagnostic]:
    """Parse pyright --outputjson output into diagnostics."""
    import json as json_mod

    try:
        data = json_mod.loads(raw)
    except (json_mod.JSONDecodeError, ValueError):
        return _parse_generic_output(raw)

    diagnostics: list[Diagnostic] = []
    for diag in data.get("generalDiagnostics", []):
        severity = diag.get("severity", "error")
        if severity not in ("error",):
            continue
        rng = diag.get("range", {}).get("start", {})
        diagnostics.append(
            Diagnostic(
                file=diag.get("file", ""),
                line=rng.get("line", 0) + 1,
                col=rng.get("character", 0) + 1,
                severity="error",
                message=diag.get("message", ""),
            )
        )
    return diagnostics


_GENERIC_DIAG_PATTERN = re.compile(r"^(.+?)\((\d+),(\d+)\):\s*(error)\s+\w+:\s*(.+)$", re.MULTILINE)
_GENERIC_DIAG_PATTERN_COLON = re.compile(r"^(.+?):(\d+):(\d+)\s*[-–]\s*(error):\s*(.+)$", re.MULTILINE)


def _parse_generic_output(raw: str) -> list[Diagnostic]:
    """Parse generic linter output (tsc/go vet style)."""
    diagnostics: list[Diagnostic] = []

    for m in _GENERIC_DIAG_PATTERN.finditer(raw):
        diagnostics.append(
            Diagnostic(
                file=m.group(1).strip(),
                line=int(m.group(2)),
                col=int(m.group(3)),
                severity=m.group(4).lower(),
                message=m.group(5).strip(),
            )
        )

    if not diagnostics:
        for m in _GENERIC_DIAG_PATTERN_COLON.finditer(raw):
            diagnostics.append(
                Diagnostic(
                    file=m.group(1).strip(),
                    line=int(m.group(2)),
                    col=int(m.group(3)),
                    severity=m.group(4).lower(),
                    message=m.group(5).strip(),
                )
            )

    return diagnostics


def _filter_diagnostics(
    diagnostics: list[Diagnostic],
    file_path: str,
    edit_line_start: int | None,
    edit_line_end: int | None,
) -> list[Diagnostic]:
    """Filter diagnostics: only errors in the edited file, optionally near edit range."""
    normalized_path = os.path.basename(file_path)

    filtered: list[Diagnostic] = []
    for d in diagnostics:
        if d.severity != "error":
            continue
        diag_basename = os.path.basename(d.file)
        if (
            diag_basename != normalized_path
            and d.file != file_path
            and not d.file.endswith(file_path)
            and not file_path.endswith(d.file)
        ):
            continue

        if edit_line_start is not None and edit_line_end is not None:
            margin = 10
            if d.line < edit_line_start - margin or d.line > edit_line_end + margin:
                continue

        filtered.append(d)

    return filtered[:MAX_REPORTED_DIAGNOSTICS]


def _format_diagnostics(diagnostics: list[Diagnostic]) -> str:
    """Format diagnostics into a clean, Agent-parseable string."""
    lines: list[str] = []
    for d in diagnostics:
        lines.append(f"  {d.file}:{d.line}:{d.col} - {d.severity}: {d.message}")
    return "\n".join(lines)


async def run_auto_verify(
    executor: CodeExecutor,
    file_path: str,
    edit_line_start: int | None = None,
    edit_line_end: int | None = None,
) -> str | None:
    """Execute auto-verify for a file after edit.

    Returns formatted diagnostic string to append to tool output, or None if
    no issues found / linter unavailable / timed out.

    Args:
        executor: Code executor for running CLI commands
        file_path: Absolute path to the edited file
        edit_line_start: Start line of the edit (1-indexed), None for CREATE
        edit_line_end: End line of the edit (1-indexed), None for CREATE
    """
    ext = os.path.splitext(file_path)[1].lower()
    config = LINTER_REGISTRY.get(ext)
    if config is None:
        return None

    if not await _check_linter_available(executor, config.detect_cmd):
        return None

    from myrm_agent_harness.toolkits.code_execution.executors.models import (
        ExecutionContext,
    )

    cmd = config.command_template.format(path=file_path)
    ctx = ExecutionContext(code=cmd, work_dir=".", timeout=AUTO_VERIFY_TIMEOUT_SECONDS)

    try:
        result = await asyncio.wait_for(
            executor.execute_bash(ctx),
            timeout=AUTO_VERIFY_TIMEOUT_SECONDS + 2,
        )
    except (TimeoutError, Exception) as e:
        logger.debug("Auto-verify timed out or failed for %s: %s", file_path, e)
        return None

    raw_output = f"{result.stdout}\n{result.stderr}".strip()
    if not raw_output or result.success:
        return None

    if ext == ".py":
        diagnostics = _parse_pyright_output(raw_output)
    else:
        diagnostics = _parse_generic_output(raw_output)

    if not diagnostics:
        return None

    filtered = _filter_diagnostics(diagnostics, file_path, edit_line_start, edit_line_end)

    if not filtered:
        return None

    formatted = _format_diagnostics(filtered)
    return f"\n[Auto-Verify] Type errors detected, please fix:\n{formatted}"
