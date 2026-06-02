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
Unified execution wrapper script.
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
            super().write("\\n\\n[System Warning: Output truncated due to size limit of {{self.limit}} bytes]\\n\\n")
            self.truncated = True
            self.current_size = self.limit
            return len(s)
        self.current_size = new_size
        return super().write(s)
'''

    allowed_hosts_str = (
        repr(set(allowed_hosts)) if allowed_hosts is not None else "None"
    )

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

def _has_asyncio_run(code: str) -> bool:
    """Check if code contains asyncio.run()."""
    return bool(re.search(r"asyncio\\.run\\s*\\(", code))


def _has_async_main_call(code: str) -> bool:
    """Check if code has async def main() with a top-level main() call.

    In this case main() returns a coroutine but doesn't execute it;
    we need to wrap it with asyncio.run().
    """
    has_async_main_def = bool(re.search(r"async\\s+def\\s+main\\s*\\(", code))
    # Check for top-level main() call (at line start)
    has_main_call = bool(re.search(r"^main\\s*\\(\\s*\\)", code, re.MULTILINE))
    return has_async_main_def and has_main_call


def _has_top_level_await(code: str) -> bool:
    """Check if code contains top-level await (await outside any function)."""
    has_await = bool(re.search(r"\\bawait\\b", code))
    has_asyncio_run_flag = _has_asyncio_run(code)
    return has_await and not has_asyncio_run_flag


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
        exec_globals = {{"__builtins__": __builtins__}}

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
            # async def main() with top-level main() call: strip call and use asyncio.run
            sanitized_code = re.sub(r"^main\\s*\\(\\s*\\)\\s*$", "", user_code, flags=re.MULTILINE)
            exec(sanitized_code, exec_globals, exec_globals)
            main_func = exec_globals.get("main")
            if callable(main_func):
                result["result"] = asyncio.run(main_func())
            else:
                result["result"] = None
        elif _has_top_level_await(user_code):
            # Top-level await mode: wrap in async function
            import textwrap
            wrapped_code = f"async def __user_code__():\\n{{textwrap.indent(user_code, '    ')}}"
            exec(wrapped_code, exec_globals, exec_globals)
            user_func = exec_globals.get("__user_code__")
            if user_func:
                result["result"] = asyncio.run(user_func())
        else:
            # Synchronous code: direct execution
            exec(user_code, exec_globals, exec_globals)
            result["result"] = None

        result["success"] = True

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
    result_match = re.search(
        r"__RESULT_START__\s*(.+?)\s*__RESULT_END__", stdout, re.DOTALL
    )

    if result_match:
        try:
            result_json = json.loads(result_match.group(1))
            # Remove result markers from stdout
            user_stdout = stdout[: result_match.start()] + stdout[result_match.end() :]
            user_stdout = user_stdout.strip()

            return ExecutionOutput(
                success=result_json.get("success", False),
                result=result_json.get("result"),
                stdout=result_json.get("stdout", user_stdout),
                stderr=result_json.get("stderr", stderr),
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
