"""Tests for CausalIssueMerger and idempotent KNOWN_ISSUES updates."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.workspace_living.merger import (
    CausalIssueMerger,
)
from myrm_agent_harness.toolkits.memory.workspace_living.models import (
    compute_error_signature,
)


class TestCausalSignature:
    def test_signature_deterministic(self) -> None:
        sig1 = compute_error_signature(
            "openssl error: cannot find symbols",
            "building crypto-core on arm64",
        )
        sig2 = compute_error_signature(
            "  OPENSSL ERROR:   cannot find symbols  ",
            "building  crypto-core   on arm64",
        )
        assert sig1 == sig2
        assert len(sig1) == 16

    def test_signature_noise_resilience(self) -> None:
        # Dynamic timestamps, pointers, and UUIDs should normalize to the same signature
        sig1 = compute_error_signature(
            "Failed at 2026-10-05T16:09:02.123Z with error at 0x7ffee1234abc (pid 1024)",
            "task 12345678-1234-1234-1234-123456789abc",
        )
        sig2 = compute_error_signature(
            "Failed at 2026-10-06 09:00:00 with error at 0x00007fffdeadbeef (pid 9999)",
            "task 87654321-4321-4321-4321-cba987654321",
        )
        assert sig1 == sig2


class TestCausalIssueMerger:
    @pytest.mark.asyncio
    async def test_initial_merge_creates_file(self, tmp_path: Path) -> None:
        merger = CausalIssueMerger(tmp_path)
        report = await merger.merge_issue(
            title="OpenSSL Build Failure",
            symptom="openssl error: missing headers",
            trigger_condition="building wheel on macOS arm64",
            workaround="export OPENSSL_DIR=$(brew --prefix openssl@3)",
        )

        assert report.added is True
        assert report.updated is False
        assert report.issue_id == "KI-001"
        assert merger.issues_file_path.is_file()

        content = merger.issues_file_path.read_text(encoding="utf-8")
        assert "### [KI-001] OpenSSL Build Failure" in content
        assert "export OPENSSL_DIR" in content
        assert "occurrences: 1" in content

    @pytest.mark.asyncio
    async def test_idempotent_duplicate_merge_updates_count(self, tmp_path: Path) -> None:
        merger = CausalIssueMerger(tmp_path)

        # First encounter
        await merger.merge_issue(
            title="OpenSSL Build Failure",
            symptom="openssl error: missing headers",
            trigger_condition="building wheel on macOS arm64",
            workaround="export OPENSSL_DIR=$(brew --prefix openssl@3)",
        )

        # Second encounter with identical symptom and trigger
        report2 = await merger.merge_issue(
            title="OpenSSL Build Failure",
            symptom="openssl error: missing headers",
            trigger_condition="building wheel on macOS arm64",
            workaround="export OPENSSL_DIR=$(brew --prefix openssl@3)",
        )

        assert report2.added is False
        assert report2.updated is True
        assert report2.issue_id == "KI-001"

        content = merger.issues_file_path.read_text(encoding="utf-8")
        assert "occurrences: 2" in content
        # Ensure only one ### [KI-001] section exists
        assert content.count("### [KI-001]") == 1

    @pytest.mark.asyncio
    async def test_different_issues_get_distinct_ids(self, tmp_path: Path) -> None:
        merger = CausalIssueMerger(tmp_path)

        rep1 = await merger.merge_issue(
            title="OpenSSL Build Failure",
            symptom="openssl error",
            trigger_condition="macOS",
            workaround="brew fix",
        )
        rep2 = await merger.merge_issue(
            title="Port Collision",
            symptom="address already in use :8080",
            trigger_condition="starting server",
            workaround="kill -9 $(lsof -t -i:8080)",
        )

        assert rep1.issue_id == "KI-001"
        assert rep2.issue_id == "KI-002"

        content = merger.issues_file_path.read_text(encoding="utf-8")
        assert "### [KI-001]" in content
        assert "### [KI-002]" in content

    @pytest.mark.asyncio
    async def test_concurrent_merge_safety(self, tmp_path: Path) -> None:
        merger = CausalIssueMerger(tmp_path)

        # 5 concurrent tasks with the same error signature
        tasks = [
            merger.merge_issue(
                title="Concurrent Hit",
                symptom="deadlock pattern",
                trigger_condition="asyncio loop",
                workaround="use lock",
            )
            for _ in range(5)
        ]
        results = await asyncio.gather(*tasks)

        # Exactly 1 added, 4 updated
        added_count = sum(1 for r in results if r.added)
        updated_count = sum(1 for r in results if r.updated)
        assert added_count == 1
        assert updated_count == 4

        content = merger.issues_file_path.read_text(encoding="utf-8")
        assert "occurrences: 5" in content
