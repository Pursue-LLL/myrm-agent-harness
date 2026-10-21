"""CLI entry point for the ACP server.

Usage:
    python -m myrm_agent_harness.agent.acp

[INPUT]
no — standard library only (runpy)

[OUTPUT]
no — delegates to ``myrm_agent_harness.agent.acp.__main__``

[POS]
Delegates to ``agent.acp.__main__``.
"""

import runpy

if __name__ == "__main__":
    runpy.run_module("myrm_agent_harness.agent.acp", run_name="__main__")
