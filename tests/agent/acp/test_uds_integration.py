"""Integration test for ACP Unix Domain Socket server and client interaction."""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile

import pytest
from acp import Client, connect_to_agent, run_agent
from acp.schema import (
    InitializeResponse,
    NewSessionResponse,
)

from myrm_agent_harness.agent.acp.default_factory import DefaultAgentFactory
from myrm_agent_harness.toolkits.acp.server.server import MyrmAcpServer


class _DummyClient(Client):
    """Minimal Client protocol implementation to receive session updates."""

    def __init__(self) -> None:
        self.updates: list[object] = []

    async def session_update(self, session_id: str, update: object, **kwargs: object) -> None:
        self.updates.append(update)


@pytest.mark.asyncio
async def test_acp_uds_server_client_roundtrip() -> None:
    """Verify ACP server running over a Unix Domain Socket can accept connections, initialize and create sessions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "test_acp.sock")

        server_instance = MyrmAcpServer(DefaultAgentFactory())

        async def _handle_server_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            # reader: client -> server; writer: server -> client
            try:
                await run_agent(server_instance, input_stream=writer, output_stream=reader)
            except Exception:
                pass
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_unix_server(_handle_server_client, path=sock_path)

        async with server:
            client_reader, client_writer = await asyncio.open_unix_connection(path=sock_path)

            client_impl = _DummyClient()
            client_conn = connect_to_agent(
                client_impl,
                client_writer,
                client_reader,
            )

            try:
                # 1. Initialize
                init_res: InitializeResponse = await client_conn.initialize(protocol_version=1)
                assert init_res.agent_info.name == "myrm-agent"
                assert init_res.protocol_version >= 1

                # 2. New Session
                sess_res: NewSessionResponse = await client_conn.new_session(cwd=tmpdir)
                assert sess_res.session_id is not None
                assert len(sess_res.session_id) > 0

            finally:
                await client_conn.close()
                client_writer.close()
                await client_writer.wait_closed()
