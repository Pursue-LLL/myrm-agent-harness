"""Shared constants for BashExecutor mixins."""

from __future__ import annotations

# MCP tool calls involve IPC + network round-trips; bash must not kill the
# process before the IPC client (TOTAL_TIMEOUT=90s) has a chance to finish.
MCP_MIN_TIMEOUT = 120
