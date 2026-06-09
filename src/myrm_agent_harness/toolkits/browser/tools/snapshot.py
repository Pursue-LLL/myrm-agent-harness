"""browser_snapshot tool for ARIA tree capture.

[INPUT]
- (none)

[OUTPUT]
- create_snapshot_tool: Create browser_snapshot tool bound to session.

[POS]
browser_snapshot tool for ARIA tree capture.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

from .common import mark_untrusted

if TYPE_CHECKING:
    from ..session import BrowserSession


def create_snapshot_tool(session: BrowserSession):
    """Create browser_snapshot tool bound to session."""

    class SnapshotInput(BaseModel):
        """Capture ARIA accessibility tree snapshot with token optimization.

        RECOMMENDED WORKFLOW (for unknown pages):
        1. browser_inspect() first → get structure metadata (~100 tokens, 15ms)
        2. Review recommendations → decide optimal params
        3. browser_snapshot(optimized_params) → get targeted snapshot

        DECISION TREE (choose optimal parameters):

        1. Unknown page structure:
           → browser_inspect() first to avoid 86% token waste

        2. Large pages (>200 refs from inspect or previous snapshot):
           → Use recommended selector from inspect
           → OR scope='interactive' + compact=True

        3. Target specific region (form, main content, article):
           → selector='#login-form' OR selector='main' (use inspect to find actual selectors)
           → Combine with scope='interactive' for precision

        4. Small pages (<50 elements from inspect):
           → Default params are optimal (skip optimization)

        5. Need full page context:
           → scope='content' (default), no selector

        PARAMETER PRIORITY: selector > scope > max_tokens

        NOTE: browser_inspect is optional. You can call browser_snapshot directly
        if you already know the page structure or need full content.
        """

        scope: str = Field(
            default="content",
            description="Snapshot scope: 'interactive' (buttons/links/inputs only), "
            "'content-only' (headings/cells/articles/images/code blocks only), "
            "'content' (default: interactive + content elements for full context), "
            "'full' (all elements including structural). "
            "Use 'interactive' for actions, 'content-only' for text extraction.",
        )
        compact: bool = Field(
            default=False,
            description="Compact single-line format (saves ~30% tokens). "
            "Recommended when metadata header shows >200 refs or >1000 tokens.",
        )
        selector: str = Field(
            default="",
            description="CSS selector to scope snapshot to a page region (e.g. '.main-content', '#login-form'). "
            "Empty = full page. Saves 50-90% tokens by limiting scope. "
            "Automatically skips iframes when set. "
            "Example: selector='#login-form' for login forms, selector='.main' for main content.",
        )
        max_tokens: int = Field(
            default=0,
            description="Truncate output to this token budget. 0 = unlimited. "
            "Set 1500-2000 when metadata header shows >2000 tokens. "
            "Note: Linear truncation may cut important content. Prefer scope/selector first.",
        )
        diff: bool = Field(
            default=True,
            description="Semantic diff since last snapshot (immune to ref renumbering). "
            "First call returns full content. Auto-resets on navigation. "
            "Set false to force full snapshot (e.g. after complex interactions).",
        )
        cursor_interactive: bool = Field(
            default=True,
            description="Detect clickable elements without ARIA roles "
            "(cursor:pointer, onclick, tabindex). Adds ~50ms. "
            "Disable if detection adds too many irrelevant elements.",
        )
        include_iframes: bool = Field(
            default=True,
            description="Include iframe content (auto-traverses all iframes). "
            "Iframe element refs use format f1_e0, f2_e1 (frame_index + ref_id). "
            "Disable to skip iframes for faster snapshots. Auto-disabled when selector is set.",
        )
        max_depth: int | None = Field(
            default=None,
            description="Limit ARIA tree depth. None = unlimited (Fast Path), int = depth limit (Custom Path). "
            "Use for deep pages: reduces traversal time by 80-85% (e.g. 800ms -> 120ms). "
            "Example: max_depth=3 for large e-commerce pages, max_depth=2 for infinite scroll.",
        )

    @tool("browser_snapshot_tool", args_schema=SnapshotInput)
    async def browser_snapshot(
        scope: str = "content",
        compact: bool = False,
        selector: str = "",
        max_tokens: int = 0,
        diff: bool = True,
        cursor_interactive: bool = True,
        include_iframes: bool = True,
        max_depth: int | None = None,
    ) -> str:
        """Get the ARIA accessibility tree of the current page (including iframes).

        Output starts with a metadata header: [N refs | ~M tokens | title | url].
        Use the ref count and token count to decide optimization parameters for next call.
        Each interactive/content element gets a ref ID (e0, e1, …) usable with browser_interact.
        Iframe elements use format f1_e0, f2_e1 (frame_index + ref_id).
        ALWAYS call this before interacting. Dialog alerts are shown at the top if any.
        """
        result = await session.snapshot(
            scope=scope,
            compact=compact,
            selector=selector,
            max_tokens=max_tokens,
            diff=diff,
            cursor_interactive=cursor_interactive,
            include_iframes=include_iframes,
            max_depth=max_depth,
        )

        # Dialog awareness: prepend pending/recent dialog info
        dialog_msg = ""
        try:
            dialog_info = session._dialog_manager.format_for_snapshot()
            if dialog_info:
                dialog_msg = dialog_info + "\n\n"
        except Exception:
            pass

        # Context-Aware Soft Routing: Check for blocking OS dialogs
        warning_msg = ""
        try:
            # Only check if computer_use is theoretically available in the environment
            # We can safely attempt to import and check
            from myrm_agent_harness.toolkits.computer_use.session import create_computer_session
            from myrm_agent_harness.toolkits.computer_use.types import KNOWN_BROWSER_NAMES, ComputerUseConfig

            # Create a lightweight session just to check backend (it caches the backend)
            cu_session = create_computer_session(ComputerUseConfig())

            # Check if the browser process has a blocking dialog
            # We pass known browser names to ensure we only trigger if the dialog belongs to the browser
            has_dialog = await cu_session.backend.has_blocking_dialog(list(KNOWN_BROWSER_NAMES))

            if has_dialog:
                warning_msg = (
                    "\n[CRITICAL ROUTING WARNING: An OS-level dialog (e.g., File Picker, Permission Prompt) "
                    "is currently blocking the web page. 'browser_interact_tool' CANNOT interact with it. "
                    "You MUST switch to 'desktop_snapshot' and 'desktop_interact_tool' immediately to handle this dialog.]\n\n"
                )
        except Exception:
            # Fail silently if computer_use is not configured or fails
            pass

        # parsesnapshotresult
        if isinstance(result, str):
            final_str = dialog_msg + warning_msg + result
            return mark_untrusted(final_str)
        if isinstance(result, tuple):
            aria_tree, _ = result
            final_str = dialog_msg + warning_msg + aria_tree
            return mark_untrusted(final_str)
        else:
            final_str = dialog_msg + warning_msg + result.aria_tree
            return mark_untrusted(final_str)

    return browser_snapshot
