"""Unit tests for ShellJobRunner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.cron.runners import ShellJobRunner
from myrm_agent_harness.toolkits.cron.types import (
    CronJob,
    DeliveryConfig,
    JobType,
    Schedule,
    ScheduleKind,
)

_SCHED = Schedule(kind=ScheduleKind.INTERVAL, interval_ms=60_000)
_NOW = datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC)


def _job(command: str | None = "echo hello") -> CronJob:
    return CronJob(
        id="j1",
        user_id="u1",
        name="test",
        job_type=JobType.SHELL,
        command=command,
        schedule=_SCHED,
        delivery=DeliveryConfig(channel="none"),
        created_at=_NOW,
        updated_at=_NOW,
    )


@dataclass
class _ExecResult:
    returncode: int
    stdout: str
    stderr: str


class TestShellJobRunner:
    @pytest.fixture
    def runner(self) -> ShellJobRunner:
        return ShellJobRunner()

    async def test_no_command(self, runner: ShellJobRunner) -> None:
        result = await runner.run(_job(command=None))
        assert result.success is False
        assert "requires a command" in (result.error or "")

    async def test_blocked_command(self, runner: ShellJobRunner) -> None:
        with patch("myrm_agent_harness.toolkits.cron.runners.has_block_threat") as mock_threat:
            mock_threat.return_value = type("Threat", (), {"detail": "dangerous", "evidence": "rm -rf"})()
            result = await runner.run(_job(command="rm -rf /"))
            assert result.success is False
            assert "blocked" in (result.error or "")

    async def test_success_exit_0(self, runner: ShellJobRunner) -> None:
        with (
            patch("myrm_agent_harness.toolkits.cron.runners.has_block_threat", return_value=None),
            patch(
                "myrm_agent_harness.toolkits.cron.runners.safe_exec",
                new_callable=AsyncMock,
                return_value=_ExecResult(returncode=0, stdout="hello\n", stderr=""),
            ),
        ):
            result = await runner.run(_job())
            assert result.success is True
            assert result.exit_code == 0
            assert result.output == "hello\n"

    async def test_success_exit_1(self, runner: ShellJobRunner) -> None:
        with (
            patch("myrm_agent_harness.toolkits.cron.runners.has_block_threat", return_value=None),
            patch(
                "myrm_agent_harness.toolkits.cron.runners.safe_exec",
                new_callable=AsyncMock,
                return_value=_ExecResult(returncode=1, stdout="diff output", stderr=""),
            ),
        ):
            result = await runner.run(_job())
            assert result.success is True
            assert result.exit_code == 1

    async def test_failure_exit_2(self, runner: ShellJobRunner) -> None:
        with (
            patch("myrm_agent_harness.toolkits.cron.runners.has_block_threat", return_value=None),
            patch(
                "myrm_agent_harness.toolkits.cron.runners.safe_exec",
                new_callable=AsyncMock,
                return_value=_ExecResult(returncode=2, stdout="", stderr="error msg"),
            ),
        ):
            result = await runner.run(_job())
            assert result.success is False
            assert result.exit_code == 2

    async def test_timeout(self, runner: ShellJobRunner) -> None:
        with (
            patch("myrm_agent_harness.toolkits.cron.runners.has_block_threat", return_value=None),
            patch(
                "myrm_agent_harness.toolkits.cron.runners.safe_exec",
                new_callable=AsyncMock,
                side_effect=TimeoutError(),
            ),
        ):
            result = await runner.run(_job())
            assert result.success is False
            assert result.exit_code == 124

    async def test_unexpected_exception(self, runner: ShellJobRunner) -> None:
        with (
            patch("myrm_agent_harness.toolkits.cron.runners.has_block_threat", return_value=None),
            patch(
                "myrm_agent_harness.toolkits.cron.runners.safe_exec",
                new_callable=AsyncMock,
                side_effect=OSError("permission denied"),
            ),
        ):
            result = await runner.run(_job())
            assert result.success is False
            assert "permission denied" in (result.error or "")


class TestNotificationRunner:
    @pytest.fixture
    def runner(self) -> "NotificationRunner":
        from myrm_agent_harness.toolkits.cron.runners import NotificationRunner

        return NotificationRunner()

    async def test_delivers_prompt(self, runner: "NotificationRunner") -> None:
        job = CronJob(
            id="r1",
            user_id="u1",
            name="reminder",
            job_type=JobType.REMINDER,
            prompt="Stand up now",
            schedule=_SCHED,
            delivery=DeliveryConfig(channel="none"),
            created_at=_NOW,
            updated_at=_NOW,
        )
        result = await runner.run(job)
        assert result.success is True
        assert result.output == "Stand up now"
        assert result.exit_code == 1

    async def test_missing_prompt(self, runner: "NotificationRunner") -> None:
        job = CronJob(
            id="r2",
            user_id="u1",
            name="reminder",
            job_type=JobType.REMINDER,
            prompt=None,
            schedule=_SCHED,
            delivery=DeliveryConfig(channel="none"),
            created_at=_NOW,
            updated_at=_NOW,
        )
        result = await runner.run(job)
        assert result.success is False
        assert "prompt" in (result.error or "").lower()
