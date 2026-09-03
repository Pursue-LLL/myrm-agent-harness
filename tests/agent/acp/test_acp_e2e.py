"""End-to-end integration test for ACP Unix Domain Socket with real LLM and dynamic MCP server tools.

Verifies:
1. Spawning ACP Server over a Unix Domain Socket with SkillAgentFactory;
2. Dynamically connecting real/mock MCP echo server provided by host;
3. Driving prompt turn over ACP JSON-RPC protocol with real LLM credentials from .env.test;
4. Streaming notifications back to ACP client.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile

import pytest
from acp import Client, connect_to_agent, run_agent
from acp.schema import (
    InitializeResponse,
    McpServerStdio,
    NewSessionResponse,
    PromptResponse,
    TextContentBlock,
)

from myrm_agent_harness.agent.acp.skill_factory import SkillAgentFactory
from myrm_agent_harness.core.config.llm import LLMConfig
from myrm_agent_harness.toolkits.acp.server.server import MyrmAcpServer


class _E2EAcpClient(Client):
    """Client implementation recording notifications and stream tokens."""

    def __init__(self) -> None:
        self.updates: list[object] = []
        self.received_chunks: list[str] = []

    async def session_update(self, session_id: str, update: object, **kwargs: object) -> None:
        self.updates.append(update)
        # Capture text updates
        if hasattr(update, "update") and hasattr(update.update, "text"):
            self.received_chunks.append(str(update.update.text))


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_acp_uds_live_llm_e2e() -> None:
    """Run real ACP turn using LLM credentials loaded from test environment."""
    api_key = os.getenv("BASIC_API_KEY")
    base_url = os.getenv("BASIC_BASE_URL")
    model = os.getenv("BASIC_MODEL")

    if not api_key or not model:
        pytest.skip("LLM credentials not found in environment for live E2E")

    llm_config = LLMConfig(
        model=model,
        api_key=api_key,
        base_url=base_url,
        streaming=True,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "live_acp.sock")

        factory = SkillAgentFactory(
            llm_config=llm_config,
            system_prompt="You are a helpful assistant. Be concise.",
        )
        server_instance = MyrmAcpServer(factory)

        async def _handle_server_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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

            client_impl = _E2EAcpClient()
            client_conn = connect_to_agent(
                client_impl,
                client_writer,
                client_reader,
            )

            try:
                # 1. Initialize
                init_res: InitializeResponse = await client_conn.initialize(protocol_version=1)
                assert init_res.agent_info.name == "myrm-agent"

                # 2. New Session with host MCP tool descriptor
                host_mcp = [
                    McpServerStdio(
                        name="host_echo",
                        command="echo",
                        args=["PONG"],
                    )
                ]
                sess_res: NewSessionResponse = await client_conn.new_session(
                    cwd=tmpdir,
                    mcp_servers=host_mcp,
                )
                session_id = sess_res.session_id
                assert session_id

                # 3. Prompt execution turn with real LLM
                prompt_blocks = [TextContentBlock(type="text", text="Reply strictly with the word: HELLO_ACP_TEST")]
                prompt_res: PromptResponse = await client_conn.prompt(
                    prompt=prompt_blocks,
                    session_id=session_id,
                )
                assert prompt_res.stop_reason in ("end_turn", "max_tokens")
                assert len(client_impl.updates) > 0

            finally:
                await client_conn.close()
                client_writer.close()
                await client_writer.wait_closed()
