"""Tests for UsageLedger JSONL auditing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.utils.token_economics.usage_ledger import (
    UsageLedger,
    UsageRecord,
)


@pytest.fixture
def ledger_dir(tmp_path: Path) -> Path:
    return tmp_path / "session"


@pytest.fixture
def ledger(ledger_dir: Path) -> UsageLedger:
    return UsageLedger(session_dir=ledger_dir)


class TestUsageRecord:
    def test_default_values(self) -> None:
        r = UsageRecord()
        assert r.model == ""
        assert r.prompt_tokens == 0
        assert r.completion_tokens == 0
        assert r.total_tokens == 0
        assert r.cached_tokens == 0
        assert r.cache_write_tokens == 0
        assert r.reasoning_tokens == 0
        assert r.citation_tokens == 0
        assert r.cost_usd == 0.0
        assert r.latency_ms == 0.0
        assert r.ttft_ms == 0.0
        assert r.finish_reason == ""
        assert r.call_index == 0

    def test_custom_values(self) -> None:
        r = UsageRecord(
            model="claude-3.5-sonnet",
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            cached_tokens=200,
            cost_usd=0.0123,
        )
        assert r.model == "claude-3.5-sonnet"
        assert r.total_tokens == 1500


class TestUsageLedger:
    def test_append_creates_dir_and_file(self, ledger: UsageLedger, ledger_dir: Path) -> None:
        record = UsageRecord(model="gpt-4o-mini", total_tokens=100)
        ledger.append(record)
        assert (ledger_dir / "usage_ledger.jsonl").exists()

    def test_append_autofills_timestamp(self, ledger: UsageLedger, ledger_dir: Path) -> None:
        record = UsageRecord(model="test")
        assert record.ts == ""
        ledger.append(record)
        line = (ledger_dir / "usage_ledger.jsonl").read_text().strip()
        data = json.loads(line)
        assert data["ts"] != ""

    def test_append_preserves_existing_timestamp(self, ledger: UsageLedger, ledger_dir: Path) -> None:
        record = UsageRecord(model="test", ts="2026-01-01T00:00:00")
        ledger.append(record)
        line = (ledger_dir / "usage_ledger.jsonl").read_text().strip()
        data = json.loads(line)
        assert data["ts"] == "2026-01-01T00:00:00"

    def test_load_empty(self, ledger: UsageLedger) -> None:
        records = ledger.load()
        assert records == []

    def test_append_and_load(self, ledger: UsageLedger) -> None:
        ledger.append(UsageRecord(model="m1", total_tokens=100, cost_usd=0.01))
        ledger.append(UsageRecord(model="m2", total_tokens=200, cost_usd=0.02))
        records = ledger.load()
        assert len(records) == 2
        assert records[0].model == "m1"
        assert records[1].model == "m2"
        assert records[0].total_tokens == 100
        assert records[1].total_tokens == 200

    def test_load_ignores_invalid_json_lines(self, ledger: UsageLedger, ledger_dir: Path) -> None:
        ledger_dir.mkdir(parents=True, exist_ok=True)
        fp = ledger_dir / "usage_ledger.jsonl"
        fp.write_text('{"model":"ok","total_tokens":1}\n{bad json}\n\n{"model":"ok2"}\n')
        records = ledger.load()
        assert len(records) == 2

    def test_load_ignores_extra_fields(self, ledger: UsageLedger, ledger_dir: Path) -> None:
        ledger_dir.mkdir(parents=True, exist_ok=True)
        fp = ledger_dir / "usage_ledger.jsonl"
        fp.write_text('{"model":"m1","total_tokens":10,"unknown_field":"ignored"}\n')
        records = ledger.load()
        assert len(records) == 1
        assert records[0].model == "m1"

    def test_get_session_summary_empty(self, ledger: UsageLedger) -> None:
        summary = ledger.get_session_summary()
        assert summary["call_count"] == 0
        assert summary["total_cost_usd"] == 0.0
        assert summary["total_tokens"] == 0

    def test_get_session_summary_with_records(self, ledger: UsageLedger) -> None:
        ledger.append(
            UsageRecord(
                model="claude-3.5-sonnet",
                prompt_tokens=1000,
                completion_tokens=500,
                total_tokens=1500,
                cached_tokens=200,
                cache_write_tokens=100,
                reasoning_tokens=50,
                citation_tokens=10,
                cost_usd=0.01,
            )
        )
        ledger.append(
            UsageRecord(
                model="gpt-4o-mini",
                prompt_tokens=500,
                completion_tokens=200,
                total_tokens=700,
                cached_tokens=100,
                cost_usd=0.005,
            )
        )
        ledger.append(
            UsageRecord(
                model="claude-3.5-sonnet",
                prompt_tokens=800,
                completion_tokens=300,
                total_tokens=1100,
                cached_tokens=300,
                cost_usd=0.008,
            )
        )
        summary = ledger.get_session_summary()
        assert summary["call_count"] == 3
        assert summary["total_tokens"] == 3300
        assert summary["input_tokens"] == 2300
        assert summary["output_tokens"] == 1000
        assert summary["cached_tokens"] == 600
        assert summary["cache_write_tokens"] == 100
        assert summary["reasoning_tokens"] == 50
        assert summary["citation_tokens"] == 10
        assert summary["cache_hit_rate"] == round(600 / 2300, 4)

        breakdown = summary["model_breakdown"]
        assert "claude-3.5-sonnet" in breakdown
        assert "gpt-4o-mini" in breakdown
        assert breakdown["claude-3.5-sonnet"]["calls"] == 2
        assert breakdown["gpt-4o-mini"]["calls"] == 1

    def test_append_error_handling(self, ledger_dir: Path) -> None:
        readonly_dir = ledger_dir / "readonly"
        readonly_dir.mkdir(parents=True)
        readonly_dir.chmod(0o444)
        ledger = UsageLedger(session_dir=readonly_dir / "nested")
        ledger.append(UsageRecord(model="test"))
        readonly_dir.chmod(0o755)

    def test_load_error_handling(self, ledger_dir: Path) -> None:
        ledger_dir.mkdir(parents=True)
        fp = ledger_dir / "usage_ledger.jsonl"
        fp.write_text("valid content")
        fp.chmod(0o000)
        ledger = UsageLedger(session_dir=ledger_dir)
        records = ledger.load()
        assert records == []
        fp.chmod(0o644)
