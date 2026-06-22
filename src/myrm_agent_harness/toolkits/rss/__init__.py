"""RSS/Atom feed fetching and parsing toolkit.

Provides a lightweight tool for agents to fetch and parse RSS/Atom feeds,
returning structured entries (title, link, summary, published) without
requiring the LLM to parse raw XML.

[OUTPUT]
- create_rss_tool: Create RSS fetch tool for agents
"""

from myrm_agent_harness.toolkits.rss.rss_agent_tools import create_rss_tool

__all__ = ["create_rss_tool"]
