"""Unit tests for EventLogger internals: enrichment, flushing, shutdown, metrics and query delegation."""

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.event_log import logger as logger_module
from myrm_agent_harness.agent.event_log.logger import EventLogger
from myrm_agent_harness.agent.event_log.protocols import EventLogBackend
from myrm_agent_harness.agent.event_log.types import BashExecutionStats, EventPayload, StructuredEvent


@pytest.fixture
def backend() -> AsyncMock:
    mock = AsyncMock(spec=EventLogBackend)
    mock.append = AsyncMock()
    mock.close = AsyncMock()
    return mock


def _appended(backend: AsyncMock) -> list[StructuredEvent]:
    return [event for call in backend.append.call_args_list for event in call[0][0]]


async def _wait_until(predicate: Callable[[], bool], timeout_s: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition not reached in time"
        await asyncio.sleep(0.01)


def _event(sequence: int = 1) -> StructuredEvent:
    return StructuredEvent(
        sequence=sequence, timestamp=1.0, event_type="tool_start", session_id="s", data=EventPayload()
    )


class TestEnrichment:
    @pytest.mark.asyncio
    async def test_context_dimensions_and_trace_id_are_injected(self, backend: AsyncMock) -> None:
        el = EventLogger(backend, "sess", user_id="u1", agent_id="a1", task_type="coding")
        with patch("myrm_agent_harness.infra.tracing.propagation.get_current_trace_id", return_value="trace-9"):
            await el.start()
            await el.log("tool_start", {"tool": "bash"})
            await el.close()

        event = next(e for e in _appended(backend) if e.event_type == "tool_start")
        assert event.data["_user_id"] == "u1"
        assert event.data["_agent_id"] == "a1"
        assert event.data["_task_type"] == "coding"
        assert event.data["_trace_id"] == "trace-9"

    @pytest.mark.asyncio
    async def test_unset_dimensions_are_omitted(self, backend: AsyncMock) -> None:
        el = EventLogger(backend, "sess")
        with patch("myrm_agent_harness.infra.tracing.propagation.get_current_trace_id", return_value=None):
            await el.start()
            await el.log("tool_start", {"tool": "bash"})
            await el.close()

        event = next(e for e in _appended(backend) if e.event_type == "tool_start")
        assert not any(key in event.data for key in ("_user_id", "_agent_id", "_task_type", "_trace_id"))


class TestSanitizeEdges:
    def test_tuples_are_redacted_element_wise(self) -> None:
        secret = "sk-test-abcdefghijklmnopqrstuvwxyz1234567890abcdef"
        result = EventLogger._sanitize({"args": (secret, 7)})
        assert isinstance(result["args"], tuple)
        assert secret not in str(result)
        assert result["args"][1] == 7

    def test_redaction_failure_persists_the_payload_as_is(self) -> None:
        data: dict[str, object] = {"k": "v"}
        with patch(
            "myrm_agent_harness.agent.security.detection.leak_detector.redact_leaks", side_effect=RuntimeError("boom")
        ):
            assert EventLogger._sanitize(data) == data


class TestSecurityAudit:
    @pytest.mark.asyncio
    async def test_decisions_are_written_and_counted(self, backend: AsyncMock) -> None:
        decision = MagicMock()
        decision.to_dict.return_value = {"verdict": "deny"}
        el = EventLogger(backend, "sess")
        with patch("myrm_agent_harness.agent.security.audit.get_audit_entries", return_value=[decision, decision]):
            await el.start()
            await el.close()

        audit = next(e for e in _appended(backend) if e.event_type == "security_audit")
        assert audit.data["count"] == 2
        end = next(e for e in _appended(backend) if e.event_type == "session_end")
        assert end.data["summary"]["security_decisions"] == 2

    @pytest.mark.asyncio
    async def test_no_decisions_writes_nothing(self, backend: AsyncMock) -> None:
        el = EventLogger(backend, "sess")
        with patch("myrm_agent_harness.agent.security.audit.get_audit_entries", return_value=[]):
            await el.start()
            await el.close()

        assert all(e.event_type != "security_audit" for e in _appended(backend))

    @pytest.mark.asyncio
    async def test_audit_failure_never_blocks_close(self, backend: AsyncMock) -> None:
        el = EventLogger(backend, "sess")
        with patch("myrm_agent_harness.agent.security.audit.get_audit_entries", side_effect=RuntimeError("boom")):
            await el.start()
            await el.close()

        assert any(e.event_type == "session_end" for e in _appended(backend))


class TestRuntimeMetrics:
    @pytest.mark.asyncio
    async def test_action_space_and_compaction_metrics_reach_the_session_end_summary(self, backend: AsyncMock) -> None:
        metrics = MagicMock(compression_count=3)
        metrics.to_dict.return_value = {"compression_count": 3}
        tracker = MagicMock()
        tracker.to_dict.return_value = {"total_tokens": 99}
        el = EventLogger(backend, "sess")
        el.set_action_space_metrics(runtime_skills=4, runtime_tools=11)
        with (
            patch("myrm_agent_harness.utils.token_economics.tracker.get_token_tracker", return_value=tracker),
            patch(
                "myrm_agent_harness.agent.context_management.tracking.task_metrics.get_task_metrics",
                return_value=metrics,
            ),
        ):
            await el.start()
            await el.close()

        summary = next(e for e in _appended(backend) if e.event_type == "session_end").data["summary"]
        assert summary["runtime_skills"] == 4
        assert summary["runtime_tools"] == 11
        assert summary["token_economics"] == {"total_tokens": 99}
        assert summary["task_metrics"] == {"compression_count": 3}
        assert summary["compactions"] == 3

    @pytest.mark.asyncio
    async def test_metric_lookup_failures_do_not_block_close(self, backend: AsyncMock) -> None:
        el = EventLogger(backend, "sess")
        with (
            patch("myrm_agent_harness.utils.token_economics.tracker.get_token_tracker", side_effect=RuntimeError("x")),
            patch(
                "myrm_agent_harness.agent.context_management.tracking.task_metrics.get_task_metrics",
                side_effect=RuntimeError("y"),
            ),
        ):
            await el.start()
            await el.close()

        assert any(e.event_type == "session_end" for e in _appended(backend))


class TestWriterLoop:
    @pytest.mark.asyncio
    async def test_idle_interval_flushes_a_partial_buffer(self, backend: AsyncMock) -> None:
        el = EventLogger(backend, "sess")
        with patch.object(logger_module, "_FLUSH_INTERVAL_S", 0.01):
            await el.start()
            await el.log("tool_start", {"tool": "bash"})
            await _wait_until(lambda: any(e.event_type == "tool_start" for e in _appended(backend)))
            await el.close()

    @pytest.mark.asyncio
    async def test_a_full_batch_is_flushed_without_waiting_for_close(self, backend: AsyncMock) -> None:
        el = EventLogger(backend, "sess")
        with patch.object(logger_module, "_FLUSH_BATCH_SIZE", 2):
            await el.start()
            await el.log("tool_start", {"tool": "bash"})
            await _wait_until(lambda: len(_appended(backend)) >= 2)
            await el.close()

    @pytest.mark.asyncio
    async def test_failed_flush_counts_dropped_events(self, backend: AsyncMock) -> None:
        backend.append.side_effect = RuntimeError("disk full")
        el = EventLogger(backend, "sess")
        el._buffer.extend([_event(1), _event(2)])

        await el._flush()

        assert el._summary.dropped_event_count == 2
        assert el._buffer == []

    @pytest.mark.asyncio
    async def test_flushing_an_empty_buffer_is_a_noop(self, backend: AsyncMock) -> None:
        await EventLogger(backend, "sess")._flush()
        backend.append.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_full_queue_drops_the_event_instead_of_blocking(self, backend: AsyncMock) -> None:
        el = EventLogger(backend, "sess")
        el._queue = asyncio.Queue(maxsize=1)
        el._queue.put_nowait(_event(1))

        await el._enqueue(_event(2))

        assert el._queue.qsize() == 1


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_runs_when_the_backend_supports_it(self, backend: AsyncMock) -> None:
        backend.cleanup_old_logs = AsyncMock(return_value=3)
        await EventLogger(backend, "sess")._cleanup_old_logs_async()
        backend.cleanup_old_logs.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_failure_is_swallowed(self, backend: AsyncMock) -> None:
        backend.cleanup_old_logs = AsyncMock(side_effect=OSError("denied"))
        await EventLogger(backend, "sess")._cleanup_old_logs_async()

    @pytest.mark.asyncio
    async def test_cleanup_is_skipped_for_backends_without_it(self) -> None:
        plain = MagicMock(spec=["append", "close"])
        await EventLogger(plain, "sess")._cleanup_old_logs_async()


class TestCloseResilience:
    @pytest.mark.asyncio
    async def test_hung_writer_is_cancelled_after_the_close_timeout(self, backend: AsyncMock) -> None:
        el = EventLogger(backend, "sess")
        el._writer_task = asyncio.create_task(asyncio.sleep(60))
        with patch.object(logger_module, "_CLOSE_TIMEOUT_S", 0.01):
            await el.close()
        await asyncio.sleep(0)
        assert el._writer_task.cancelled()

    @pytest.mark.asyncio
    async def test_final_flush_and_backend_close_errors_are_swallowed(self, backend: AsyncMock) -> None:
        backend.append.side_effect = RuntimeError("append failed")
        backend.close.side_effect = RuntimeError("close failed")
        el = EventLogger(backend, "sess")
        el._buffer.append(_event())

        await el.close()

        assert el._buffer == []

    @pytest.mark.asyncio
    async def test_cli_summary_failure_never_blocks_close(self, backend: AsyncMock) -> None:
        el = EventLogger(backend, "sess")
        with patch(
            "myrm_agent_harness.agent.event_log.cli_summary.generate_cli_summary", side_effect=RuntimeError("fmt")
        ):
            await el.start()
            await el.close()

        assert any(e.event_type == "session_end" for e in _appended(backend))


class TestQueryDelegation:
    @pytest.mark.asyncio
    async def test_tool_usage_stats_forward_the_time_range(self, backend: AsyncMock) -> None:
        with patch(
            "myrm_agent_harness.agent.event_log.analytics_queries.get_tool_usage_stats", new_callable=AsyncMock
        ) as query:
            query.return_value = []
            assert await EventLogger(backend, "sess").get_tool_usage_stats(time_range_seconds=60) == []
        query.assert_awaited_once_with(backend, "sess", time_range_seconds=60)

    @pytest.mark.asyncio
    async def test_activity_patterns_forward_the_time_range(self, backend: AsyncMock) -> None:
        with patch(
            "myrm_agent_harness.agent.event_log.analytics_queries.get_activity_patterns", new_callable=AsyncMock
        ) as query:
            await EventLogger(backend, "sess").get_activity_patterns(time_range_seconds=30)
        query.assert_awaited_once_with(backend, "sess", time_range_seconds=30)

    @pytest.mark.asyncio
    async def test_bash_audit_logs_forward_every_filter(self, backend: AsyncMock) -> None:
        with patch(
            "myrm_agent_harness.agent.event_log.analytics_queries.get_bash_audit_logs", new_callable=AsyncMock
        ) as query:
            query.return_value = []
            await EventLogger(backend, "sess").get_bash_audit_logs(
                start_time=1.0, end_time=2.0, command_type="WRITE", risk_level="HIGH", limit=5
            )
        query.assert_awaited_once_with(
            backend, "sess", start_time=1.0, end_time=2.0, command_type="WRITE", risk_level="HIGH", limit=5
        )

    @pytest.mark.asyncio
    async def test_bash_execution_stats_are_flattened_to_a_dict(self, backend: AsyncMock) -> None:
        stats = BashExecutionStats(
            total_commands=4,
            success_rate=0.75,
            avg_duration_ms=12.5,
            error_top10=[("boom", 1)],
            command_hotmap=[("ls", 3)],
            type_distribution={"READ": 3},
            hourly_breakdown=[(9, 4)],
        )
        with patch(
            "myrm_agent_harness.agent.event_log.analytics_queries.get_bash_execution_stats", new_callable=AsyncMock
        ) as query:
            query.return_value = stats
            result = await EventLogger(backend, "sess").get_bash_execution_stats()

        assert result == {
            "total_commands": 4,
            "success_rate": 0.75,
            "avg_duration_ms": 12.5,
            "error_top10": [("boom", 1)],
            "command_hotmap": [("ls", 3)],
            "type_distribution": {"READ": 3},
            "hourly_breakdown": [(9, 4)],
        }
