"""Tests for consensus type definitions."""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.consensus import (
    ConsensusConfig,
    ConsensusResult,
    ReferenceResponse,
)


class TestConsensusConfig:
    def test_default_values(self):
        cfg = ConsensusConfig()
        assert cfg.reference_temperature == 0.6
        assert cfg.aggregator_temperature == 0.4
        assert cfg.min_successful == 1
        assert cfg.timeout_per_model == 120.0
        assert cfg.timeout_total == 300.0
        assert cfg.max_retries_per_model == 2
        assert cfg.reference_max_tokens is None

    def test_frozen(self):
        cfg = ConsensusConfig()
        import pytest

        with pytest.raises(AttributeError):
            cfg.min_successful = 5  # type: ignore[misc]

    def test_custom_values(self):
        cfg = ConsensusConfig(
            reference_temperature=0.8,
            aggregator_temperature=0.2,
            min_successful=3,
            timeout_per_model=60.0,
            timeout_total=180.0,
            max_retries_per_model=5,
            reference_max_tokens=600,
        )
        assert cfg.reference_temperature == 0.8
        assert cfg.aggregator_temperature == 0.2
        assert cfg.min_successful == 3
        assert cfg.max_retries_per_model == 5
        assert cfg.reference_max_tokens == 600


class TestReferenceResponse:
    def test_success_response(self):
        r = ReferenceResponse(
            model="test/model",
            content="Hello",
            elapsed_seconds=1.5,
            success=True,
        )
        assert r.model == "test/model"
        assert r.content == "Hello"
        assert r.success
        assert r.error is None

    def test_failure_response(self):
        r = ReferenceResponse(
            model="test/fail",
            content="",
            elapsed_seconds=0.5,
            success=False,
            error="timeout",
        )
        assert not r.success
        assert r.error == "timeout"


class TestConsensusResult:
    def test_success_result(self):
        refs = [
            ReferenceResponse(model="a", content="c", elapsed_seconds=1.0, success=True),
        ]
        r = ConsensusResult(
            final_answer="Final",
            reference_responses=refs,
            aggregator_model="agg",
            elapsed_seconds=3.0,
        )
        assert r.success
        assert r.final_answer == "Final"
        assert r.error is None

    def test_failure_result(self):
        r = ConsensusResult(
            final_answer="",
            success=False,
            error="insufficient models",
        )
        assert not r.success
        assert r.error == "insufficient models"

    def test_default_values(self):
        r = ConsensusResult(final_answer="OK")
        assert r.reference_responses == []
        assert r.aggregator_model == ""
        assert r.elapsed_seconds == 0.0
        assert r.success is True
        assert r.error is None
