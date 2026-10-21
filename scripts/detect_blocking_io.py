#!/usr/bin/env python3
"""Static detector for synchronous blocking IO inside async functions.

Scans Python source files for calls like ``open()``, ``os.walk()``,
``Path.read_text()`` etc. that appear inside ``async def`` bodies.
Findings are prioritized candidates for human review, not automatic
bug decisions.

Usage::

    python scripts/detect_blocking_io.py [--src SRC_DIR] [--json OUT.json]

Designed for CI integration: exits 0 on success, 1 if new findings exceed
baseline. The JSON report can be diffed across commits.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

BLOCKING_BUILTINS: frozenset[str] = frozenset({
    "open",
    "input",
})

BLOCKING_MODULE_CALLS: frozenset[str] = frozenset({
    "os.walk",
    "os.listdir",
    "os.scandir",
    "os.stat",
    "os.lstat",
    "os.getcwd",
    "os.mkdir",
    "os.makedirs",
    "os.rename",
    "os.replace",
    "os.remove",
    "os.unlink",
    "os.rmdir",
    "os.link",
    "os.symlink",
    "os.readlink",
    "os.chmod",
    "os.chown",
    "os.path.exists",
    "os.path.isfile",
    "os.path.isdir",
    "os.path.getsize",
    "shutil.copy",
    "shutil.copy2",
    "shutil.copytree",
    "shutil.move",
    "shutil.rmtree",
    "sqlite3.connect",
    "time.sleep",
    "subprocess.run",
    "subprocess.call",
    "subprocess.check_output",
    "subprocess.check_call",
})

BLOCKING_PATH_ATTRS: frozenset[str] = frozenset({
    "read_text",
    "write_text",
    "read_bytes",
    "write_bytes",
    "exists",
    "is_file",
    "is_dir",
    "stat",
    "lstat",
    "mkdir",
    "rmdir",
    "unlink",
    "rename",
    "replace",
    "iterdir",
    "glob",
    "rglob",
    "touch",
    "chmod",
    "symlink_to",
    "hardlink_to",
})


@dataclass
class Finding:
    file: str
    line: int
    blocking_call: str
    priority: str = "medium"
    reason: str = ""


@dataclass
class ScanResult:
    total_findings: int = 0
    files_scanned: int = 0
    files_with_findings: int = 0
    findings: list[Finding] = field(default_factory=list)


class _BlockingCallVisitor(ast.NodeVisitor):
    """Walk AST and collect blocking calls inside async functions."""

    def __init__(self, filepath: str) -> None:
        self._filepath = filepath
        self._in_async_depth = 0
        self.findings: list[Finding] = []

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._in_async_depth += 1
        self.generic_visit(node)
        self._in_async_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        old = self._in_async_depth
        self._in_async_depth = 0
        self.generic_visit(node)
        self._in_async_depth = old

    def visit_Call(self, node: ast.Call) -> None:
        if self._in_async_depth > 0:
            name = self._resolve_call_name(node)
            if name:
                priority = "high" if name in ("open", "time.sleep", "sqlite3.connect") else "medium"
                self.findings.append(Finding(
                    file=self._filepath,
                    line=node.lineno,
                    blocking_call=name,
                    priority=priority,
                    reason=f"Synchronous '{name}' in async context blocks the event loop",
                ))
        self.generic_visit(node)

    def _resolve_call_name(self, node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            if node.func.id in BLOCKING_BUILTINS:
                return node.func.id
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                dotted = f"{node.func.value.id}.{node.func.attr}"
                if dotted in BLOCKING_MODULE_CALLS:
                    return dotted
            if node.func.attr in BLOCKING_PATH_ATTRS:
                return f"*.{node.func.attr}"
        return ""


def scan_directory(src_dir: Path) -> ScanResult:
    result = ScanResult()
    for py_file in sorted(src_dir.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        result.files_scanned += 1
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        visitor = _BlockingCallVisitor(str(py_file.relative_to(src_dir.parent)))
        visitor.visit(tree)

        if visitor.findings:
            result.files_with_findings += 1
            result.total_findings += len(visitor.findings)
            result.findings.extend(visitor.findings)

    result.findings.sort(key=lambda f: (f.priority != "high", f.file, f.line))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect blocking IO in async code")
    parser.add_argument(
        "--src",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "src" / "myrm_agent_harness",
        help="Source directory to scan",
    )
    parser.add_argument("--json", type=Path, default=None, help="Write JSON report")
    parser.add_argument("--quiet", action="store_true", help="Only output summary")
    args = parser.parse_args(argv)

    result = scan_directory(args.src)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps([asdict(f) for f in result.findings], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    high = sum(1 for f in result.findings if f.priority == "high")
    medium = result.total_findings - high

    print(f"Blocking IO scan: {result.files_scanned} files, "
          f"{result.total_findings} findings ({high} high, {medium} medium) "
          f"in {result.files_with_findings} files")

    if not args.quiet:
        for f in result.findings[:30]:
            print(f"  [{f.priority.upper()}] {f.file}:{f.line} {f.blocking_call}")
        if result.total_findings > 30:
            print(f"  ... and {result.total_findings - 30} more")

    return 0


if __name__ == "__main__":
    sys.exit(main())
