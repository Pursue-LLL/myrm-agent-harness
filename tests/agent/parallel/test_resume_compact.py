"""Tests for parallel resume payload compaction."""

from __future__ import annotations

from unittest.mock import patch

from myrm_agent_harness.agent.parallel.resume_compact import (
    compact_batch_results_for_resume,
)


def test_compact_batch_results_vaults_large_result() -> None:
    large_result = "x" * 12000
    batch = {
        "success": True,
        "results": [
            {
                "success": True,
                "result": large_result,
                "agent_type": "research",
                "task_index": 0,
            }
        ],
    }

    with patch(
        "myrm_agent_harness.agent.parallel.resume_compact._auto_vault_or_truncate",
        return_value="vault://abc123 summary",
    ) as vault_mock:
        compacted = compact_batch_results_for_resume(
            batch,
            workspace_path="/tmp/workspace",
            vault_threshold=8000,
        )

    vault_mock.assert_called_once()
    results = compacted["results"]
    assert isinstance(results, list)
    assert results[0]["result"] == "vault://abc123 summary"


def test_compact_batch_results_skips_small_payload() -> None:
    batch = {
        "success": True,
        "results": [{"success": True, "result": "short", "agent_type": "general"}],
    }
    compacted = compact_batch_results_for_resume(batch, workspace_path="/tmp/workspace")
    assert compacted is batch


def test_resolve_max_parallel_fission_defaults() -> None:
    from myrm_agent_harness.agent.parallel.config import (
        DEFAULT_MAX_PARALLEL_FISSION,
        MAX_PARALLEL_FISSION_CAP,
        resolve_max_parallel_fission,
    )

    assert resolve_max_parallel_fission(None) == DEFAULT_MAX_PARALLEL_FISSION
    assert resolve_max_parallel_fission(99) == MAX_PARALLEL_FISSION_CAP
    assert resolve_max_parallel_fission(2) == 2
