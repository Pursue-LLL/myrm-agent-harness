"""LangChain tools for interactive browser automation.

Eight semantically grouped tools covering browser capabilities:
- browser_navigate — open a URL
- browser_inspect  — analyze page structure quickly (lightweight metadata, ~15ms, ~100 tokens)
- browser_snapshot — perceive the page via ARIA accessibility tree (with diff, scope, compact)
- browser_interact — act on elements by ref (13 actions: click, type, fill, press, hover, select, scroll, etc.)
- browser_extract  — get page text, screenshot, or diff screenshot (with configurable parameters)
- browser_manage   — tabs, JS eval, history, dialogs, PDF, resize, session vault, recording, site experience, downloads (29 actions)
- browser_execute_script_tool — execute a Python script for batch browser actions using Code-as-Action paradigm
- browser_ask_human — request user takeover when automation is insufficient (2FA, payment, MFA)

Screenshot Diff Features:
- Fast strategy: dHash perceptual hash (~2ms), ideal for quick change detection
- Accurate strategy: Canvas API pixel-level comparison (~100ms), with YIQ color space and anti-aliasing detection
- Auto strategy: automatically selects based on image size (<800x600 → accurate, ≥800x600 → fast)
- Configurable parameters: similarity_threshold, color_tolerance, mismatch_threshold, include_aa


[INPUT]
- session::BrowserSession (POS: session manager, based on SOLID principles)
- langchain.tools::tool (POS: LangChain tool decorator)
- pydantic::BaseModel (POS: tool parameter schema base class)

[OUTPUT]
- create_browser_tools: factory function, binds BrowserSession and returns 8 LangChain tools

[POS]
API layer of the browser toolkit. Maps BrowserSession capabilities to 8 LangChain @tool functions,
loaded on-demand by the Agent runtime. Pure thin layer, zero business logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .common import mark_untrusted
from .execute_script import create_execute_script_tool
from .extract import create_extract_tool
from .inspect import create_inspect_tool
from .interact import create_interact_tool
from .manage import create_manage_tool
from .navigate import create_navigate_tool
from .snapshot import create_snapshot_tool
from .takeover import create_takeover_tool

if TYPE_CHECKING:
    from ..session import BrowserSession

# Backward compatibility alias for tests
_mark_untrusted = mark_untrusted

__all__ = ["_mark_untrusted", "create_browser_tools"]


def create_browser_tools(session: BrowserSession) -> list:
    """Create the 8 browser tools bound to *session*.

    Args:
        session: BrowserSession instance

    Returns:
        List of 8 LangChain tools
    """
    return [
        create_navigate_tool(session),
        create_inspect_tool(session),
        create_snapshot_tool(session),
        create_interact_tool(session),
        create_extract_tool(session),
        create_manage_tool(session),
        create_execute_script_tool(session),
        create_takeover_tool(session),
    ]
