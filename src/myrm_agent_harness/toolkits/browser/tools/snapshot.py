"""browser_snapshot tool for ARIA tree capture.

[INPUT]
- common::mark_untrusted (POS: unified browser output security boundary; credential redaction + untrusted-content wrapping)
- session.browser_session::BrowserSession (POS: browser session aggregate root; snapshot + extractor visual content detection)

[OUTPUT]
- create_snapshot_tool: Create browser_snapshot tool bound to session.

[POS]
browser_snapshot tool for ARIA tree capture. Auto-detects canvas/rich-editor visual content via
Extractor.detect_significant_visual_content() and appends [VISUAL_CONTENT_DETECTED] hint.
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
        """Capture ARIA accessibility tree snapshot with element references for interaction.

        WORKFLOW & BEST PRACTICES:
        - Call this before interacting with page elements to obtain fresh ref IDs (e0, e1, etc.).
        - For complex/large pages, specify 'selector' or scope='interactive' to keep output focused.
        - When snapshot output contains [VISUAL_CONTENT_DETECTED] (canvas/rich-editors like Google Docs, Figma),
          switch to coordinate mode in browser_interact_tool (x/y parameters).
        """

        scope: str = Field(
            default="content",
            description="Snapshot scope: 'interactive' (buttons/links/inputs only), "
            "'content-only' (headings/cells/articles/images/code blocks only), "
            "'content' (default: interactive + content elements for full context), "
            "'full' (all elements including structural). "
            "Use 'interactive' for action planning, 'content-only' for text extraction.",
        )
        compact: bool = Field(
            default=False,
            description="Compact single-line format for element tree. "
            "Recommended for large pages to keep context concise.",
        )
        selector: str = Field(
            default="",
            description="CSS selector to scope snapshot to a specific page region (e.g. 'main', '#login-form', '.content'). "
            "Empty string captures the full page. Automatically skips iframes when set.",
        )
        max_tokens: int = Field(
            default=0,
            description="Truncate output to this token budget (0 = unlimited). "
            "Set 1500-2000 for extremely long pages. Prefer using 'selector' or 'scope' first.",
        )
        diff: bool = Field(
            default=True,
            description="Semantic diff returning only elements changed since last snapshot. "
            "First call returns full content. Automatically resets on navigation. "
            "Set False to force a full snapshot (e.g. after major page transitions).",
        )
        cursor_interactive: bool = Field(
            default=True,
            description="Detect clickable elements without explicit ARIA roles (cursor:pointer, onclick, tabindex). "
            "Disable if detection includes too many non-essential elements.",
        )
        include_iframes: bool = Field(
            default=True,
            description="Include iframe content (auto-traverses all iframes). "
            "Iframe element refs use format f1_e0, f2_e1 (frame_index + ref_id). "
            "Disable to skip iframes for faster snapshots. Automatically disabled when selector is set.",
        )
        max_depth: int | None = Field(
            default=None,
            description="Limit ARIA tree depth (e.g. max_depth=3 for deep e-commerce/feed pages). "
            "None = unlimited depth.",
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

        Output starts with metadata header: [N refs | ~M tokens | title | url].
        Each interactive/content element gets a unique ref ID (e0, e1, …) usable with browser_interact_tool.
        Iframe elements use format f1_e0, f2_e1 (frame_index + ref_id).
        ALWAYS call this tool to inspect the page before using browser_interact_tool.
        Pending dialog alerts and OS-level blocking warnings will appear at the top if present.
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

        # Visual content detection: hint agent to use coordinate mode
        visual_hint = ""
        try:
            if session._extractor and await session._extractor.detect_significant_visual_content():
                visual_hint = (
                    "\n[VISUAL_CONTENT_DETECTED: This page contains canvas/rich-editor content (e.g. Google Docs, "
                    "Figma, Sheets). DOM refs may not map to visible elements. Prefer using screenshot + coordinate "
                    "interactions (browser_interact with x/y parameters) for accurate targeting.]\n\n"
                )
        except Exception:
            pass

        if isinstance(result, str):
            final_str = dialog_msg + warning_msg + visual_hint + result
            return mark_untrusted(final_str)
        if isinstance(result, tuple):
            aria_tree, _ = result
            final_str = dialog_msg + warning_msg + visual_hint + aria_tree
            return mark_untrusted(final_str)
        else:
            final_str = dialog_msg + warning_msg + visual_hint + result.aria_tree
            return mark_untrusted(final_str)

    return browser_snapshot
