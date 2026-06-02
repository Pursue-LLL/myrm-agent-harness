"""CLI entry point for the ACP server.

Usage:
    python -m myrm_agent_harness.agent.acp

IDE integration:
    Configure your IDE to start this process as an ACP agent:
    {
        "command": "python",
        "args": ["-m", "myrm_agent_harness.agent.acp"]
    }

[INPUT]
- (none)

[OUTPUT]
- main: Parse execution output from the wrapper script.

[POS]
CLI entry point for the ACP server.
"""

from __future__ import annotations

import asyncio
import logging
import sys


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    from myrm_agent_harness.toolkits.acp.server.server import run_server

    try:
        from myrm_agent_harness.agent.acp.default_factory import DefaultAgentFactory

        factory = DefaultAgentFactory()
    except (ImportError, TypeError):
        logging.error(
            "No AgentFactory implementation found or module broken. "
            "Ensure myrm_agent_harness.agent is available "
            "or provide your own factory."
        )
        sys.exit(1)

    asyncio.run(run_server(factory))


if __name__ == "__main__":
    main()
