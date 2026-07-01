"""Shared constants for BashExecutor mixins.

[INPUT]
- None

[OUTPUT]
- MCP_MIN_TIMEOUT: Minimum bash timeout when MCP skill IPC is active

[POS]
Internal constants module; re-exported as _MCP_MIN_TIMEOUT from bash_executor aggregate.
"""

from __future__ import annotations

# MCP tool calls involve IPC + network round-trips; bash must not kill the
# process before the IPC client (TOTAL_TIMEOUT=90s) has a chance to finish.
MCP_MIN_TIMEOUT = 120
