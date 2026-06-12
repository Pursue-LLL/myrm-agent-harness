"""Tool management utilities.

[OUTPUT]
- with_dynamic_hints: Decorator to safely inject cross-tool dependency hints.
"""

from myrm_agent_harness.utils.tool_dynamic_hints import with_dynamic_hints

__all__ = ["with_dynamic_hints"]
