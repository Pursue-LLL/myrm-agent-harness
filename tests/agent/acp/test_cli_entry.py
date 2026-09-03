"""Comprehensive edge-case and CLI option tests for ACP server entry point."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.acp.__main__ import _create_factory
from myrm_agent_harness.agent.acp.default_factory import DefaultAgentFactory
from myrm_agent_harness.agent.acp.skill_factory import SkillAgentFactory


def test_create_factory_choices() -> None:
    skill_fac = _create_factory("skill")
    assert isinstance(skill_fac, SkillAgentFactory)

    default_fac = _create_factory("default")
    assert isinstance(default_fac, DefaultAgentFactory)

    unknown_fac = _create_factory("other")
    assert isinstance(unknown_fac, DefaultAgentFactory)


def test_main_cli_arguments_parser() -> None:
    def _mock_run(coro: object) -> None:
        if hasattr(coro, "close"):
            coro.close()

    with patch("argparse.ArgumentParser.parse_args") as mock_args, patch(
        "asyncio.run",
        side_effect=_mock_run,
    ) as mock_asyncio_run:
        mock_args.return_value = MagicMock(
            agent_type="skill",
            transport="stdio",
            socket_path="/tmp/test.sock",
            verbose=True,
        )

        from myrm_agent_harness.agent.acp.__main__ import main

        main()
        mock_asyncio_run.assert_called_once()
