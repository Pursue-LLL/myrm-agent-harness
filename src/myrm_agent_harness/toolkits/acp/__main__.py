"""CLI entry point for the ACP server.

Usage:
    python -m myrm_agent_harness.agent.acp

[POS]
Delegates to ``agent.acp.__main__``.
"""

import runpy
import sys

if __name__ == "__main__":
    sys.exit(runpy.run_module("myrm_agent_harness.agent.acp", run_name="__main__"))
