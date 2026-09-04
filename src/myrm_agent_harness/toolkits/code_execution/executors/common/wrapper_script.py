"""Unified execution wrapper script.

Shared wrapper for all executors. Handles:
1. Execution mode detection (asyncio.run vs top-level await)
2. C-level PEP 578 Audit Sandbox injection
3. Unified JSON output format
4. Matplotlib inline figure capture (Jupyter-grade, via vault:// zero-copy pointers)

[INPUT]
- toolkits.code_execution.security.audit_sandbox::install (POS: Install PEP 578 audit hook)

[OUTPUT]
- ExecutionOutput: Parsed execution output.
- BoundedStringIO: Bounded buffer to prevent log bomb.
- generate_wrapper_script: Generate the execution wrapper script.
- main: Parse execution output from the wrapper script.
- parse_execution_output: function — parse_execution_output

[POS]
Unified execution wrapper script. User-code stderr is not captured inside the
wrapper (only stdout is bounded); parse_execution_output therefore merges the
subprocess stderr pipe (user sys.stderr writes) with the JSON stderr key
(wrapper-captured traceback) so neither diagnostic stream is discarded.
"""

import json
import re
from dataclasses import dataclass


@dataclass
class ExecutionOutput:
    """Parsed execution output."""

    success: bool
    result: object | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None


def generate_wrapper_script(
    code_file_path: str = "/workspace/user_code.py",
    allow_network: bool = False,
    allowed_hosts: frozenset[str] | None = None,
    timeout: int | None = None,
    memory_limit_mb: int | None = None,
    max_output_bytes: int = 5 * 1024 * 1024,
) -> str:
    """Generate the execution wrapper script.

    Args:
        code_file_path: Path to the user code file.
        allow_network: Whether to allow network access.
        allowed_hosts: Host whitelist (only effective when allow_network=True).
        timeout: Hard CPU timeout in seconds.
        memory_limit_mb: Hard memory limit in MB.
        max_output_bytes: Max size for stdout buffer to prevent memory overflow.

    Returns:
        Wrapper script content.
    """
    # Generate OS Resource Limits code
    limits_setup = []
    if timeout is not None:
        limits_setup.append(
            f"    try:\n        resource.setrlimit(resource.RLIMIT_CPU, ({timeout}, {timeout} + 5))\n    except (ValueError, OSError):\n        pass"
        )
    if memory_limit_mb is not None and memory_limit_mb > 0:
        limit_bytes = memory_limit_mb * 1024 * 1024
        limits_setup.append(
            f"    try:\n        resource.setrlimit(resource.RLIMIT_AS, ({limit_bytes}, {limit_bytes}))\n    except (ValueError, OSError):\n        pass"
        )
    limits_setup.append(
        "    try:\n        resource.setrlimit(resource.RLIMIT_NPROC, (512, 512))\n    except (ValueError, OSError):\n        pass"
    )
    limits_setup.append(
        "    try:\n        resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))\n    except (ValueError, OSError):\n        pass"
    )
    limits_setup.append(
        "    try:\n        resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024 * 1024, 100 * 1024 * 1024))\n    except (ValueError, OSError):\n        pass"
    )

    limits_str = "\n".join(limits_setup)

    resource_limits_code = f"""
# ============================================================
# OS Resource Limits
# ============================================================
try:
    import resource
{limits_str}
except ImportError:
    pass
"""

    # Generate BoundedStringIO
    bounded_stringio_code = f'''
class BoundedStringIO(io.StringIO):
    """Bounded buffer to prevent log bomb."""
    def __init__(self, limit={max_output_bytes}, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.limit = limit
        self.current_size = 0
        self.truncated = False

    def write(self, s):
        if self.truncated:
            return len(s)
        new_size = self.current_size + len(s)
        if new_size > self.limit:
            allowed = self.limit - self.current_size
            super().write(s[:allowed])
            super().write("\\n\\n[System Warning: Output truncated due to size limit of {{limit}} bytes]\\n\\n".format(limit=self.limit))
            self.truncated = True
            self.current_size = self.limit
            return len(s)
        self.current_size = new_size
        return super().write(s)
'''

    allowed_hosts_str = repr(set(allowed_hosts)) if allowed_hosts is not None else "None"

    return f'''#!/usr/bin/env python3
"""Unified execution wrapper script.

Auto-detects execution mode:
1. asyncio.run() mode: direct execution
2. Top-level await mode: wrapped execution
"""

import asyncio
import io
import json
import os
import re
import sys
import traceback

{resource_limits_code}

{bounded_stringio_code}

# ============================================================
# Execution mode detection
# ============================================================

def _collect_async_runners(tree: object) -> set[str]:
    """Collect all callable names that act as asyncio.run (including aliases and imports)."""
    import ast

    runners = {{"asyncio.run"}}
    if not isinstance(tree, ast.AST):
        return runners

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "asyncio":
            for alias in node.names:
                if alias.name == "run":
                    runners.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "asyncio" and alias.asname:
                    runners.add(f"{{alias.asname}}.run")
    return runners


def _has_asyncio_run(code: str) -> bool:
    """Check if code contains a real asyncio.run() Call node (or alias) via AST."""
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    runners = _collect_async_runners(tree)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "run":
                if isinstance(func.value, ast.Name):
                    call_name = f"{{func.value.id}}.run"
                    if call_name in runners:
                        return True
            elif isinstance(func, ast.Name):
                if func.id in runners:
                    return True
    return False


def _has_async_main_call(code: str) -> bool:
    """Check if code defines an async main() and invokes main() as a top-level statement or inside if __name__ == '__main__': block without await/asyncio.run."""
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    has_async_main_def = False
    for stmt in tree.body:
        if isinstance(stmt, ast.AsyncFunctionDef) and stmt.name == "main":
            has_async_main_def = True
            break

    if not has_async_main_def:
        return False

    runners = _collect_async_runners(tree)

    class _MainCallDetector(ast.NodeVisitor):
        def __init__(self):
            self.calls_main_unawaited = False

        def visit_FunctionDef(self, node):
            pass

        def visit_AsyncFunctionDef(self, node):
            pass

        def visit_ClassDef(self, node):
            pass

        def visit_Await(self, node):
            # Awaited calls (e.g. await main() or res = await main()) are properly scheduled
            pass

        def visit_Call(self, node):
            # Skip runners that take care of scheduling coroutines
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in (
                "run",
                "create_task",
                "run_until_complete",
            ):
                return
            if isinstance(func, ast.Name) and func.id in runners:
                return
            if isinstance(func, ast.Name) and func.id == "main":
                self.calls_main_unawaited = True
            self.generic_visit(node)

    detector = _MainCallDetector()
    for stmt in tree.body:
        detector.visit(stmt)
        if detector.calls_main_unawaited:
            return True
    return False


def _has_top_level_await(code: str) -> bool:
    """Check if code contains top-level await (await/async for/async with outside any function)."""
    import ast

    class _TopLevelAsyncVisitor(ast.NodeVisitor):
        def __init__(self):
            self.has_top_level = False

        def visit_FunctionDef(self, node):
            pass

        def visit_AsyncFunctionDef(self, node):
            pass

        def visit_ClassDef(self, node):
            pass

        def visit_Await(self, node):
            self.has_top_level = True

        def visit_AsyncFor(self, node):
            self.has_top_level = True

        def visit_AsyncWith(self, node):
            self.has_top_level = True

    try:
        tree = ast.parse(code)
    except SyntaxError:
        has_await = bool(re.search(r"\\\\bawait\\\\b", code))
        return has_await and not _has_asyncio_run(code)

    visitor = _TopLevelAsyncVisitor()
    for stmt in tree.body:
        visitor.visit(stmt)
        if visitor.has_top_level:
            return True
    return False


def _wrap_top_level_async_user_code(user_code: str) -> str:
    """Wrap code with an async function while keeping future imports and headers at file top."""
    import textwrap

    header_lines = []
    body_lines = []
    in_header = True
    for line in user_code.splitlines():
        stripped = line.strip()
        if in_header:
            if not stripped or stripped.startswith("#") or stripped.startswith("from __future__ import"):
                header_lines.append(line)
                continue
            in_header = False
        body_lines.append(line)

    header_part = chr(10).join(header_lines)
    body_part = textwrap.indent(chr(10).join(body_lines), "    ")
    return f"{{header_part}}\\nasync def __user_code__():\\n{{body_part}}\\n"


# ============================================================
# Code split marker
# ============================================================

USER_CODE_MARKER = "# === User Code ==="


def _split_code(full_code: str) -> tuple[str, str]:
    """Split MCP client code from user code.

    Args:
        full_code: Full code (may contain MCP client + user code).

    Returns:
        (mcp_code, user_code) tuple.
    """
    if USER_CODE_MARKER in full_code:
        parts = full_code.split(USER_CODE_MARKER, 1)
        return parts[0].strip(), parts[1].strip()
    return "", full_code


# ============================================================
# Main execution logic
# ============================================================

def main():
    result = {{"success": False, "result": None, "error": None, "stdout": "", "stderr": ""}}

    # Capture stdout with bounded string buffer
    captured_stdout = BoundedStringIO()
    original_stdout = sys.stdout

    try:
        # Read full code
        with open("{code_file_path}", "r", encoding="utf-8") as f:
            full_code = f.read()

        # Split MCP client code and user code
        mcp_code, user_code = _split_code(full_code)

        mcp_globals = {{"__builtins__": __builtins__}}

        # Phase 1: Execute MCP client code (before sandbox locks down)
        if mcp_code:
            exec(mcp_code, mcp_globals, mcp_globals)

        # Phase 2: Install PEP 578 Audit Hook to lock down the process
        # Using the framework's native security engine
        from myrm_agent_harness.toolkits.code_execution.security import audit_sandbox

        # We need the workspace path. The executor resolves it and sets cwd.
        workspace_path = os.getcwd()

        audit_sandbox.install(
            workspace_path=workspace_path,
            allow_network={allow_network},
            allowed_hosts={allowed_hosts_str}
        )

        # Phase 3: Create user code execution env (inheriting builtins naturally, but heavily secured by PEP 578)
        exec_globals = {{
            "__builtins__": __builtins__,
            "__name__": "__main__",
            "__file__": "{code_file_path}",
            "__doc__": None,
        }}

        # Pass MCP client objects to user code (skills.xxx accessible)
        for key in ["skills", "MCPError", "_call", "_Pkg", "_Mod", "_FuncProxy"]:
            if key in mcp_globals:
                exec_globals[key] = mcp_globals[key]

        # Also pass skills module from sys.modules
        if "skills" in sys.modules:
            exec_globals["skills"] = sys.modules["skills"]

        # JS/JSON literal compatibility for LLM-generated code
        exec_globals["null"] = None
        exec_globals["true"] = True
        exec_globals["false"] = False
        exec_globals["undefined"] = None

        # Redirect stdout
        sys.stdout = captured_stdout

        # Matplotlib headless hook — Jupyter-grade inline figure capture.
        # Surfaces every OPEN figure as a zero-copy vault:// pointer: both
        # multi-figure scripts calling plt.show() and notebook-style code
        # that omits show() produce visible inline images.
        _myrm_flush_figures = None
        try:
            import builtins
            import time
            import uuid
            original_import = builtins.__import__

            def _myrm_emit_open_figures():
                # Emit + close every open figure. Closing after emit makes the set
                # of open figures the single source of truth, so plt.show() and the
                # end-of-run flush never double-render the same figure.
                import matplotlib.pyplot as plt
                for _num in plt.get_fignums():
                    fig = plt.figure(_num)
                    os.makedirs(".myrm_plots", exist_ok=True)
                    plot_id = f"plot_{{int(time.time())}}_{{uuid.uuid4().hex[:8]}}.webp"
                    filepath = os.path.join(".myrm_plots", plot_id)
                    fig.savefig(filepath, format="webp", bbox_inches="tight")
                    plt.close(fig)
                    original_stdout.write(f"\\x1b_MyrmImage:vault://.myrm_plots/{{plot_id}},w=80,h=24\\x1b\\\\\\n")
                    original_stdout.flush()

            _myrm_flush_figures = _myrm_emit_open_figures

            def custom_import(name, globals=None, locals=None, fromlist=(), level=0):
                mod = original_import(name, globals, locals, fromlist, level)
                # Intercept matplotlib.pyplot or matplotlib
                if name == "matplotlib.pyplot" or (name == "matplotlib" and fromlist and "pyplot" in fromlist):
                    try:
                        import matplotlib
                        matplotlib.use("Agg", force=True)
                        import matplotlib.pyplot as plt
                        if not hasattr(plt, "_myrm_patched"):
                            def myrm_show(*args, **kwargs):
                                _myrm_emit_open_figures()
                            plt.show = myrm_show
                            plt._myrm_patched = True
                    except Exception:
                        pass
                return mod
            builtins.__import__ = custom_import
        except Exception:
            pass

        # Detect execution mode and run user code
        if _has_asyncio_run(user_code):
            # Standard asyncio mode: run in new thread (avoid nested event loop)
            import concurrent.futures

            def run_in_thread():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    exec(user_code, exec_globals, exec_globals)
                finally:
                    loop.close()

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_thread)
                future.result()

            result["result"] = None
        elif _has_async_main_call(user_code):
            # async def main() with unawaited main() call: execute module and drive main() with asyncio.run
            exec(user_code, exec_globals, exec_globals)
            main_func = exec_globals.get("main")
            if callable(main_func):
                result["result"] = asyncio.run(main_func())
            else:
                result["result"] = None
        elif _has_top_level_await(user_code):
            # Top-level await mode: wrap in async function while preserving future imports at file top
            wrapped_code = _wrap_top_level_async_user_code(user_code)
            exec(wrapped_code, exec_globals, exec_globals)
            user_func = exec_globals.get("__user_code__")
            if user_func:
                result["result"] = asyncio.run(user_func())
        else:
            # Synchronous code: direct execution
            exec(user_code, exec_globals, exec_globals)
            result["result"] = None

        result["success"] = True

    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        if exit_code == 0:
            result["success"] = True
            result["error"] = None
        else:
            result["success"] = False
            result["error"] = f"SystemExit: {{e.code}}"
    except Exception as e:
        result["error"] = f"{{type(e).__name__}}: {{str(e)}}"
        result["stderr"] = traceback.format_exc()

    finally:
        # Flush remaining figures before restoring stdout. Runs on both
        # success and error paths so partially-built plots still surface
        # (matches Jupyter: cell errors don't discard prior display output).
        if _myrm_flush_figures is not None and "matplotlib.pyplot" in sys.modules:
            try:
                _myrm_flush_figures()
            except Exception:
                pass

        # Restore stdout
        sys.stdout = original_stdout
        result["stdout"] = captured_stdout.getvalue()

    # Output result
    print("__RESULT_START__")
    print(json.dumps(result, default=str))
    print("__RESULT_END__")


if __name__ == "__main__":
    main()
'''


def parse_execution_output(stdout: str, stderr: str, exit_code: int) -> ExecutionOutput:
    """Parse execution output from the wrapper script.

    Args:
        stdout: Standard output.
        stderr: Standard error.
        exit_code: Exit code.

    Returns:
        Parsed ExecutionOutput.
    """
    result_match = re.search(r"__RESULT_START__\s*(.+?)\s*__RESULT_END__", stdout, re.DOTALL)

    if result_match:
        try:
            result_json = json.loads(result_match.group(1))
            # Remove result markers from stdout
            user_stdout = stdout[: result_match.start()] + stdout[result_match.end() :]
            user_stdout = user_stdout.strip()

            json_stderr = result_json.get("stderr") or ""
            pipe_stderr = stderr or ""
            # The wrapper only captures a traceback into the JSON stderr key;
            # user sys.stderr writes (logs, progress) stay in the subprocess
            # pipe. Both carry diagnostics, so merge instead of preferring one:
            # pipe-first (user output precedes the exception) then the JSON
            # traceback. When the pipe already carries the traceback (wrapper
            # crash path) it is kept verbatim so nothing is duplicated.
            if not json_stderr:
                merged_stderr = pipe_stderr
            elif not pipe_stderr or json_stderr in pipe_stderr:
                merged_stderr = pipe_stderr or json_stderr
            else:
                merged_stderr = f"{pipe_stderr.rstrip()}\n\n{json_stderr}"

            return ExecutionOutput(
                success=result_json.get("success", False),
                result=result_json.get("result"),
                stdout=result_json.get("stdout", user_stdout),
                stderr=merged_stderr,
                error=result_json.get("error"),
            )
        except json.JSONDecodeError:
            pass

    # Fallback: use raw output if JSON parsing fails
    return ExecutionOutput(
        success=exit_code == 0,
        result=None,
        stdout=stdout,
        stderr=stderr,
        error=stderr if exit_code != 0 else None,
    )
