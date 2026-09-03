"""CLI entry point for the ACP server.

Usage:
    # Stdio transport (default, standard IDE ACP connection)
    python -m myrm_agent_harness.agent.acp

    # Full SkillAgent with dynamic tools
    python -m myrm_agent_harness.agent.acp --agent-type skill

    # Unix Domain Socket transport
    python -m myrm_agent_harness.agent.acp --transport socket --socket-path /tmp/myrm_acp.sock

[INPUT]
- agent.acp.default_factory::DefaultAgentFactory (POS: Minimal BaseAgent factory) [lazy]
- agent.acp.skill_factory::SkillAgentFactory (POS: Full-featured SkillAgent factory) [lazy]
- toolkits.acp.server.server::run_server (POS: ACP server runner over streams) [lazy]

[OUTPUT]
- main: CLI entry point supporting stdio and UDS transports

[POS]
CLI entry point for standalone ACP server daemon.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.acp.server.bridge import AgentFactory

logger = logging.getLogger(__name__)


def _create_factory(agent_type: str) -> AgentFactory:
    """Instantiate the requested AgentFactory."""
    if agent_type == "skill":
        from myrm_agent_harness.agent.acp.skill_factory import SkillAgentFactory

        return SkillAgentFactory()

    from myrm_agent_harness.agent.acp.default_factory import DefaultAgentFactory

    return DefaultAgentFactory()


async def _run_unix_socket_server(factory: AgentFactory, socket_path: str) -> None:
    """Run ACP server listening on a Unix Domain Socket."""
    from myrm_agent_harness.toolkits.acp.server.server import run_server

    sock_file = Path(socket_path)
    if sock_file.exists():
        try:
            sock_file.unlink()
        except OSError as exc:
            logger.warning("failed_to_unlink_existing_socket path=%s error=%s", socket_path, exc)

    sock_file.parent.mkdir(parents=True, exist_ok=True)

    async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        logger.info("acp_uds_client_connected socket=%s", socket_path)
        try:
            # reader serves as output_stream (read from client), writer serves as input_stream (write to client)
            await run_server(factory, input_stream=writer, output_stream=reader)
        except Exception as exc:
            logger.info("acp_uds_client_session_ended socket=%s error=%s", socket_path, exc)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_unix_server(_handle_client, path=socket_path)
    logger.info("acp_uds_server_listening socket=%s", socket_path)

    try:
        async with server:
            await server.serve_forever()
    finally:
        if sock_file.exists():
            try:
                sock_file.unlink()
            except OSError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Myrm ACP Agent Server Daemon")
    parser.add_argument(
        "--agent-type",
        choices=["skill", "default"],
        default="skill",
        help="Agent assembly type: 'skill' (full SkillAgent) or 'default' (minimal BaseAgent). Defaults to skill.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "socket"],
        default="stdio",
        help="Transport type: 'stdio' or 'socket' (Unix Domain Socket). Defaults to stdio.",
    )
    parser.add_argument(
        "--socket-path",
        default=os.getenv("MYRM_ACP_SOCKET_PATH", "/tmp/myrm_acp.sock"),
        help="Path for Unix Domain Socket when transport=socket.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG level logging.",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        factory = _create_factory(args.agent_type)
    except Exception as exc:
        logger.error("Failed to initialize AgentFactory: %s", exc)
        sys.exit(1)

    if args.transport == "socket":
        asyncio.run(_run_unix_socket_server(factory, args.socket_path))
    else:
        from myrm_agent_harness.toolkits.acp.server.server import run_server

        asyncio.run(run_server(factory))


if __name__ == "__main__":
    main()
