"""Architecture gate: component snapshots bounded diff validation.

Asserts that tool layers, middleware stack, context strategies, and system defaults
do not experience silent behavioral or schema drift from canonical baseline snapshots.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from harness_packaging.component_snapshots import (
    compute_bounded_diff,
    export_all_snapshots,
    get_snapshots_dir,
)


@pytest.mark.architecture
def test_component_snapshots_exist() -> None:
    """Verify that all 4 canonical component snapshots exist on disk."""
    snapshots_dir = get_snapshots_dir()
    assert snapshots_dir.is_dir(), f"Missing snapshots directory: {snapshots_dir}"

    expected_files = [
        "tool_surface_snapshot.json",
        "middleware_stack_snapshot.json",
        "context_strategies_snapshot.json",
        "system_defaults_snapshot.json",
    ]
    for filename in expected_files:
        snapshot_file = snapshots_dir / filename
        assert (
            snapshot_file.is_file()
        ), f"Missing component snapshot file: {snapshot_file}"


@pytest.mark.architecture
def test_component_snapshots_bounded_diff_clean() -> None:
    """Assert zero bounded diff between live harness component exports and baseline snapshots."""
    snapshots_dir = get_snapshots_dir()
    baseline_data: dict[str, object] = {}

    for key in (
        "tool_surface",
        "middleware_stack",
        "context_strategies",
        "system_defaults",
    ):
        file_path = snapshots_dir / f"{key}_snapshot.json"
        baseline_data[key] = json.loads(file_path.read_text(encoding="utf-8"))

    current_data = export_all_snapshots()
    diffs = compute_bounded_diff(current_data, baseline_data)

    if diffs:
        diff_report = "\n  - ".join(diffs)
        pytest.fail(
            f"Component snapshot bounded diff detected (silent architectural drift):\n  - {diff_report}\n\n"
            f"If this change is intentional, update baseline via: "
            f"`python myrm-agent-harness/scripts/update_component_snapshots.py`"
        )


@pytest.mark.architecture
def test_compute_bounded_diff_detects_layer_and_config_mismatch() -> None:
    """Assert compute_bounded_diff captures synthetic tool layer and system default diffs."""
    mock_base = {
        "tool_surface": [{"name": "mock_tool", "layer": "CORE", "layer_value": 10}],
        "middleware_stack": [
            {"symbol": "mock_mw", "present": True, "type": "function"}
        ],
        "context_strategies": [
            {"strategy": "summary", "symbol": "mock_sym", "present": True}
        ],
        "system_defaults": {"k1": "v1"},
    }
    mock_curr = {
        "tool_surface": [
            {"name": "mock_tool", "layer": "COMMON", "layer_value": 20},
            {"name": "new_tool", "layer": "CORE", "layer_value": 10},
        ],
        "middleware_stack": [
            {"symbol": "mock_mw", "present": True, "type": "function"}
        ],
        "context_strategies": [
            {"strategy": "summary", "symbol": "mock_sym", "present": True}
        ],
        "system_defaults": {"k1": "v2"},
    }
    diffs = compute_bounded_diff(mock_curr, mock_base)
    assert len(diffs) >= 3
    diff_text = " ".join(diffs)
    assert "Added tools" in diff_text
    assert "Layer mismatch" in diff_text
    assert "Configuration mismatch" in diff_text
