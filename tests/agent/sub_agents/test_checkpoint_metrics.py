"""Tests for CheckpointMetrics data structures."""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.checkpoint.metrics import CheckpointMetrics


class TestCheckpointMetrics:
    def test_default_values(self) -> None:
        m = CheckpointMetrics()
        assert m.save_count == 0
        assert m.save_success_count == 0
        assert m.save_failure_count == 0
        assert m.save_total_ms == 0.0
        assert m.resume_count == 0
        assert m.total_checkpoints == 0
        assert m.messages_extracted_count == 0

    def test_save_success_rate_zero_when_no_saves(self) -> None:
        m = CheckpointMetrics()
        assert m.save_success_rate == 0.0

    def test_save_success_rate_calculation(self) -> None:
        m = CheckpointMetrics(save_count=10, save_success_count=8)
        assert m.save_success_rate == 0.8

    def test_save_avg_ms_zero_when_no_saves(self) -> None:
        m = CheckpointMetrics()
        assert m.save_avg_ms == 0.0

    def test_save_avg_ms_calculation(self) -> None:
        m = CheckpointMetrics(save_count=4, save_total_ms=200.0)
        assert m.save_avg_ms == 50.0

    def test_resume_success_rate_zero_when_no_resumes(self) -> None:
        m = CheckpointMetrics()
        assert m.resume_success_rate == 0.0

    def test_resume_success_rate_calculation(self) -> None:
        m = CheckpointMetrics(resume_count=5, resume_success_count=4)
        assert m.resume_success_rate == 0.8

    def test_resume_avg_ms_zero_when_no_resumes(self) -> None:
        m = CheckpointMetrics()
        assert m.resume_avg_ms == 0.0

    def test_resume_avg_ms_calculation(self) -> None:
        m = CheckpointMetrics(resume_count=2, resume_total_ms=100.0)
        assert m.resume_avg_ms == 50.0

    def test_total_size_mb(self) -> None:
        m = CheckpointMetrics(total_size_bytes=1048576)
        assert m.total_size_mb == 1.0

    def test_total_size_mb_zero(self) -> None:
        m = CheckpointMetrics()
        assert m.total_size_mb == 0.0

    def test_messages_extraction_success_rate_zero_when_no_extractions(self) -> None:
        m = CheckpointMetrics()
        assert m.messages_extraction_success_rate == 0.0

    def test_messages_extraction_success_rate_calculation(self) -> None:
        m = CheckpointMetrics(messages_extracted_count=7, messages_extraction_failures=3)
        assert m.messages_extraction_success_rate == 0.7

    def test_to_dict_contains_all_keys(self) -> None:
        m = CheckpointMetrics(
            save_count=10,
            save_success_count=9,
            save_failure_count=1,
            save_total_ms=500.0,
            resume_count=5,
            resume_success_count=4,
            resume_failure_count=1,
            resume_total_ms=200.0,
            total_checkpoints=3,
            total_size_bytes=2048,
            messages_extracted_count=8,
            messages_extraction_failures=2,
        )
        d = m.to_dict()

        assert d["save_count"] == 10
        assert d["save_success_count"] == 9
        assert d["save_failure_count"] == 1
        assert d["save_success_rate"] == 0.9
        assert d["save_avg_ms"] == 50.0
        assert d["save_total_ms"] == 500.0
        assert d["resume_count"] == 5
        assert d["resume_success_count"] == 4
        assert d["resume_failure_count"] == 1
        assert d["resume_success_rate"] == 0.8
        assert d["resume_avg_ms"] == 40.0
        assert d["resume_total_ms"] == 200.0
        assert d["total_checkpoints"] == 3
        assert d["total_size_bytes"] == 2048
        assert d["total_size_mb"] == 2048 / (1024 * 1024)
        assert d["messages_extracted_count"] == 8
        assert d["messages_extraction_failures"] == 2
        assert d["messages_extraction_success_rate"] == 0.8

    def test_to_dict_with_defaults(self) -> None:
        m = CheckpointMetrics()
        d = m.to_dict()
        assert d["save_success_rate"] == 0.0
        assert d["resume_success_rate"] == 0.0
        assert d["messages_extraction_success_rate"] == 0.0
