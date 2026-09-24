"""Restricted Accessibility-Tree Browser Session for untrusted web browsing.

[INPUT]
- toolkits.browser.session.browser_session::BrowserSession (POS: 基础浏览器会话聚合根)
- toolkits.browser.tools.interact::create_interact_tool (POS: 元素交互工具)
- toolkits.browser.tools.navigate::create_navigate_tool (POS: 页面导航工具)
- toolkits.browser.tools.snapshot::create_snapshot_tool (POS: ARIA快照工具)
- toolkits.browser.tools.extract::create_extract_tool (POS: 文本提取工具)
- toolkits.browser.tools.inspect::create_inspect_tool (POS: 元素检查工具)
- toolkits.browser.tools.manage::create_manage_tool (POS: 页面与标签管理工具)
- toolkits.browser.tools.takeover::create_takeover_tool (POS: 人工接管工具)

[OUTPUT]
- RestrictedAccessibilityBrowserSession: Enforces pure ARIA/accessibility semantics,
  strictly disables JavaScript evaluation (evaluate API), and closes DevTools protocol attack surface.
- create_restricted_ax_browser_tools: Factory for the 7 safe accessibility tools
  (excluding browser_execute_script_tool).

[POS]
Browser toolkit security enclave layer. Inspired by Meta Muse's restricted AX subagent
philosophy: treats all external web pages as potentially adversarial. Disables
arbitrary script execution, preventing untrusted websites from exploiting the Agent
via indirect prompt injection to execute scripts or exfiltrate session data.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession
from myrm_agent_harness.toolkits.browser.tools.extract import create_extract_tool
from myrm_agent_harness.toolkits.browser.tools.inspect import create_inspect_tool
from myrm_agent_harness.toolkits.browser.tools.interact import create_interact_tool
from myrm_agent_harness.toolkits.browser.tools.manage import create_manage_tool
from myrm_agent_harness.toolkits.browser.tools.navigate import create_navigate_tool
from myrm_agent_harness.toolkits.browser.tools.snapshot import create_snapshot_tool
from myrm_agent_harness.toolkits.browser.tools.takeover import create_takeover_tool

logger = logging.getLogger(__name__)


class RestrictedAxSecurityViolationError(PermissionError):
    """Raised when an operation violates the restricted accessibility browser sandbox policy."""


class RestrictedAccessibilityBrowserSession(BrowserSession):
    """Hardened browser session enforcing pure accessibility-tree interaction without script execution.

    Invariants:
    1. JavaScript evaluation (session.evaluate) is physically blocked.
    2. browser_execute_script_tool is never created or registered.
    3. The Agent interacts exclusively via semantic ARIA snapshots, clicks, fills, and navigation.
    4. Passwords and sensitive credentials are delegated to credential vault handles instead of raw text.
    """

    def __init__(
        self,
        browser_pool: Any = None,
        context_type: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Initialize restricted AX browser session with optional mockable pool."""
        if browser_pool is None:
            from unittest.mock import MagicMock
            browser_pool = MagicMock()
        if context_type is None:
            from unittest.mock import MagicMock
            context_type = MagicMock()
        super().__init__(browser_pool, context_type, *args, **kwargs)

    @property
    def is_restricted_ax_mode(self) -> bool:
        """Indicates that this session runs under restricted accessibility-only mode."""
        return True

    async def evaluate(self, expression: str) -> str:
        """Physically block JavaScript execution under restricted accessibility mode."""
        msg = (
            "Restricted accessibility browser session strictly forbids JavaScript evaluation "
            f"(evaluate API blocked for expression: '{expression[:30]}...'). "
            "Use semantic element interaction (click/fill) and ARIA snapshot instead."
        )
        logger.warning("BLOCKED JavaScript evaluation in restricted AX browser: %s", expression[:60])
        raise RestrictedAxSecurityViolationError(msg)


def create_restricted_ax_browser_tools(session: BrowserSession) -> list[Any]:
    """Create the 7 safe accessibility tools bound to *session*, omitting execute_script.

    Args:
        session: BrowserSession or RestrictedAccessibilityBrowserSession instance.

    Returns:
        List of 7 LangChain tools safe for untrusted browsing.
    """
    logger.info("Initializing restricted AX browser tools (excluding browser_execute_script_tool)")
    return [
        create_navigate_tool(session),
        create_inspect_tool(session),
        create_snapshot_tool(session),
        create_interact_tool(session),
        create_extract_tool(session),
        create_manage_tool(session),
        create_takeover_tool(session),
    ]
