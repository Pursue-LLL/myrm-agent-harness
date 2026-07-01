"""Integration test for resume_compact without mocking _auto_vault_or_truncate."""

from __future__ import annotations

import re
from pathlib import Path

from myrm_agent_harness.agent.artifacts.vault import ArtifactVault
from myrm_agent_harness.agent.parallel.resume_compact import compact_batch_results_for_resume


def test_compact_batch_results_vaults_large_result_real(tmp_path: Path) -> None:
    ws = str(tmp_path)
    marker = "FISSION_MARKER_" + ("payload-" * 300)
    batch = {
        "success": True,
        "results": [
            {
                "success": True,
                "result": marker,
                "agent_type": "research",
                "task_index": 0,
            }
        ],
    }

    compacted = compact_batch_results_for_resume(batch, workspace_path=ws, vault_threshold=500)
    assert compacted is not batch
    result_text = compacted["results"][0]["result"]
    assert isinstance(result_text, str)
    match = re.search(r"vault://[a-f0-9-]+", result_text)
    assert match is not None

    vault = ArtifactVault(ws)
    assert vault.get(match.group(0)).decode("utf-8") == marker
