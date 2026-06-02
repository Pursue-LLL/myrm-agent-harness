"""Local browser data search toolkit.

Provides Agent access to local Chromium-based browser (Chrome/Edge)
bookmarks and browsing history for URL discovery.


[INPUT]
- tool::create_local_browser_data_tool (POS: tool factory function)

[OUTPUT]
- create_local_browser_data_tool: creates a local browser data search tool

[POS]
Local browser data search toolkit entry point. Exports the tool factory function.
"""

from .local_browser_data_agent_tools import create_local_browser_data_tool

__all__ = ["create_local_browser_data_tool"]
