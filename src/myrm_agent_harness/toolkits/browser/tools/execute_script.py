"""browser_execute_script tool for Code-as-Action batch execution.

[INPUT]
- patchright.async_api::Page (POS: Patchright page instance)
- session.browser_session::BrowserSession (POS: browser session)

[OUTPUT]
- create_execute_script_tool: Create browser_execute_script tool bound to session.

[POS]
Allows the agent to write and execute a Python script to perform batch browser actions,
bypassing the single-step bottleneck. Sets `session._hitl_caller_tool` for semantic HITL audit
attribution during script execution. Uses AST transformation to inject async yields,
preventing event loop blocking, and restricts globals for safety.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import io
import logging
import textwrap
from typing import TYPE_CHECKING, Any

from langchain.tools import tool
from pydantic import BaseModel, Field

from .common import mark_untrusted

if TYPE_CHECKING:
    from ..session import BrowserSession

logger = logging.getLogger(__name__)


_PRIVILEGED_API_METHODS = frozenset({"get", "post", "put", "delete", "patch", "fetch", "head"})
_PRIVILEGED_API_ATTRS = frozenset({"request", "context", "evaluate", "evaluate_handle", "new_page", "new_context"})


class _PrivilegedAPIScanner(ast.NodeVisitor):
    """Detect Playwright privileged API access that bypasses domain filter / HITL guards.

    page.request.* bypasses context.route() entirely (Playwright official behavior).
    page.evaluate() bypasses enforce_js_eval_guard (only triggered via browser_manage).
    page.context gives access to unprotected context operations.
    """

    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Attribute):
            parent_attr = node.value.attr
            if parent_attr == "request" and node.attr in _PRIVILEGED_API_METHODS:
                self.violations.append(f".request.{node.attr}()")
        if node.attr in _PRIVILEGED_API_ATTRS:
            if isinstance(node.ctx, ast.Load):
                if isinstance(node.value, ast.Name) and node.value.id in ("session", "refs"):
                    pass
                else:
                    self.violations.append(f".{node.attr}")
        self.generic_visit(node)


async def _require_privileged_api_approval(
    session: BrowserSession, violations: list[str], script_preview: str
) -> str | None:
    """Trigger HITL approval when script uses APIs that bypass domain filter."""
    from langgraph.types import interrupt

    from myrm_agent_harness.core.security.audit import record_decision

    apis = ", ".join(violations)
    logger.warning(
        "[SCRIPT_PRIVILEGED_API] Detected privileged API access: %s", apis
    )
    record_decision("browser_execute_script_tool", "ASK", f"Privileged API: {apis}")

    user_response = interrupt({
        "action_type": "script_privileged_api",
        "tool_name": "browser_execute_script_tool",
        "reason": f"Script accesses privileged APIs that bypass network policy: {apis}",
        "violations": violations,
        "script_preview": script_preview[:500],
    })

    if isinstance(user_response, dict) and user_response.get("decision") == "approve":
        record_decision("browser_execute_script_tool", "USER_APPROVED", f"Privileged API approved: {apis}")
        return None
    if isinstance(user_response, str) and user_response.lower() in ("approve", "allow", "yes", "y"):
        record_decision("browser_execute_script_tool", "USER_APPROVED", f"Privileged API approved: {apis}")
        return None

    record_decision("browser_execute_script_tool", "USER_REJECTED", f"Privileged API rejected: {apis}")
    feedback = ""
    if isinstance(user_response, dict):
        feedback = str(user_response.get("feedback", "") or "")
    return (
        f"[BLOCKED] Script uses privileged APIs ({apis}) that bypass network security policy. "
        f"User rejected execution."
        + (f" Feedback: {feedback}" if feedback else "")
        + " Rewrite the script using session.interact() instead."
    )


class _AsyncYieldInjector(ast.NodeTransformer):
    """Injects `await asyncio.sleep(0)` into every loop to prevent event loop blocking."""

    def visit_While(self, node: ast.While) -> ast.While:
        self.generic_visit(node)
        sleep_expr = ast.Expr(
            value=ast.Await(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id="asyncio", ctx=ast.Load()),
                        attr="sleep",
                        ctx=ast.Load(),
                    ),
                    args=[ast.Constant(value=0)],
                    keywords=[],
                )
            )
        )
        node.body.insert(0, sleep_expr)
        return node

    def visit_For(self, node: ast.For) -> ast.For:
        self.generic_visit(node)
        sleep_expr = ast.Expr(
            value=ast.Await(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id="asyncio", ctx=ast.Load()),
                        attr="sleep",
                        ctx=ast.Load(),
                    ),
                    args=[ast.Constant(value=0)],
                    keywords=[],
                )
            )
        )
        node.body.insert(0, sleep_expr)
        return node


def create_execute_script_tool(session: BrowserSession):
    """Create browser_execute_script tool bound to session."""

    class ExecuteScriptInput(BaseModel):
        """Execute a Python script for batch browser actions.

        Use this tool to perform multiple steps (e.g., filling a form, scraping a list)
        in a single turn. The script has access to `session` and `refs` (a dict mapping
        ref IDs to their metadata).

        You can use `await session.interact(action, ref, text)` directly in the script!
        Example:
        ```python
        await session.interact("fill", "e1", "John")
        await session.interact("fill", "e2", "password")
        await session.interact("click", "e3")
        print("Form submitted successfully!")
        ```

        You can also use raw Playwright via `page = session._tab_controller.get_active_page()`.
        Use `print()` to output information; it will be returned as the tool result.
        """

        script: str = Field(
            description="The async Python script to execute. Do not include `async def` wrapper, just the body."
        )
        verify_goal: str | None = Field(
            default=None,
            description="Optional. A natural language description of what you expect to see after this script finishes (e.g., 'Success message is shown'). If provided, the tool will take screenshots before and after, and use a Vision LLM to verify if the goal was met, returning the visual feedback directly to you.",
        )

    @tool("browser_execute_script_tool", args_schema=ExecuteScriptInput)
    async def browser_execute_script(script: str, verify_goal: str | None = None) -> str:
        """Execute a Python script to perform batch browser actions."""

        # 1. Prepare the ARIA refs mapping
        refs_info = session.get_all_refs()
        refs_dict = {
            ref_id: {
                "role": info.role,
                "name": info.name,
                "nth": info.nth,
            }
            for ref_id, info in refs_info.items()
        }

        # 2. Wrap the script in an async function
        wrapped_code = "async def __agent_step__(session, refs):\n"
        wrapped_code += textwrap.indent(script, "    ")

        # 3. Parse and transform AST to prevent infinite loops blocking the event loop
        try:
            tree = ast.parse(wrapped_code)
            tree = _AsyncYieldInjector().visit(tree)
            ast.fix_missing_locations(tree)
            safe_code = ast.unparse(tree)
        except SyntaxError as e:
            return f"SyntaxError in script: {e}"
        except Exception as e:
            return f"Failed to parse script: {e}"

        # 3.5. Scan for privileged Playwright API access that bypasses network policy
        scanner = _PrivilegedAPIScanner()
        scanner.visit(tree)
        if scanner.violations:
            unique = sorted(set(scanner.violations))
            blocked = await _require_privileged_api_approval(session, unique, script)
            if blocked:
                return blocked

        # 4. Prepare safe globals
        import builtins

        safe_builtins = {
            k: getattr(builtins, k)
            for k in dir(builtins)
            if k
            not in (
                "__import__",
                "eval",
                "exec",
                "open",
                "exit",
                "quit",
                "compile",
                "getattr",
                "setattr",
                "delattr",
            )
        }

        output_buffer = io.StringIO()
        print_queue = asyncio.Queue()

        def custom_print(*args: object, **_kwargs: object) -> None:
            text = " ".join(str(a) for a in args)
            output_buffer.write(text + "\n")
            print_queue.put_nowait(text)

        async def stream_flusher():
            while True:
                text = await print_queue.get()
                if text is None:
                    break
                with contextlib.suppress(Exception):
                    await session.notify_progress(f"[Script] {text}")
                print_queue.task_done()

        flusher_task = asyncio.create_task(stream_flusher())

        globals_dict: dict[str, Any] = {
            "__builtins__": safe_builtins,
            "asyncio": asyncio,
            "print": custom_print,
        }
        locals_dict: dict[str, Any] = {}

        # 5. Compile and execute the function definition
        try:
            exec(safe_code, globals_dict, locals_dict)
        except Exception as e:
            return f"Compilation error: {e}"

        func = locals_dict.get("__agent_step__")
        if not func:
            return "Execution error: __agent_step__ function not found."

        # 6. Run the function with a timeout
        baseline_screenshot = None
        if verify_goal:
            try:
                page = session._tab_controller.get_active_page()
                from myrm_agent_harness.toolkits.browser.utils.selectors import PASSWORD_FIELD_SELECTOR

                password_locator = page.locator(PASSWORD_FIELD_SELECTOR)
                baseline_screenshot = await page.screenshot(type="png", full_page=False, mask=[password_locator])
            except Exception as e:
                logger.warning("Failed to take baseline screenshot for verification: %s", e)

        session._hitl_caller_tool = "browser_execute_script_tool"
        try:
            await session.notify_progress("Starting browser script execution...")
            # Run with a 60-second timeout
            await asyncio.wait_for(func(session, refs_dict), timeout=60.0)
        except TimeoutError:
            output_buffer.write("\n[Error] Script execution timed out after 60 seconds.")
        except Exception:
            import traceback

            error_trace = traceback.format_exc()
            output_buffer.write(f"\n[Error] Runtime exception:\n{error_trace}")
        finally:
            session._hitl_caller_tool = None
            print_queue.put_nowait(None)
            await flusher_task
            await session.notify_progress("Browser script execution completed.")

        # 7. Verification
        if verify_goal and baseline_screenshot:
            try:
                page = session._tab_controller.get_active_page()
                await session.notify_progress(f"Verifying script goal: '{verify_goal}'...")
                _success, verify_msg = await session._vision_verifier.verify_action(
                    page=page,
                    baseline_screenshot=baseline_screenshot,
                    verify_goal=verify_goal,
                )
                output_buffer.write(f"\n\n{verify_msg}")
            except Exception as e:
                output_buffer.write(f"\n\nVerification failed: {e}")

        # 8. Return the captured output
        result_output = output_buffer.getvalue().strip()
        if not result_output:
            result_output = "Script executed successfully with no output."

        return mark_untrusted(result_output)

    return browser_execute_script
