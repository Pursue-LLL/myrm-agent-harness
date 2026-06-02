"""Import hot path performance regression tests.

Keep the public entry points and security hot paths fast in a fresh Python process.
"""

from __future__ import annotations

import statistics
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.xdist_group("import_perf")

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
RUNS_PER_CASE: Final[int] = 3

pytestmark = pytest.mark.performance


def _measure_import_median_ms(import_statement: str) -> float:
    """Measure a fresh-process import statement in milliseconds."""
    samples: list[float] = []
    script = (
        f"import time\nstart = time.perf_counter()\n{import_statement}\nprint((time.perf_counter() - start) * 1000)\n"
    )

    for _ in range(RUNS_PER_CASE):
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        samples.append(float(completed.stdout.strip()))

    return statistics.median(samples)


@pytest.mark.parametrize(
    ("import_statement", "threshold_ms"),
    [
        ("import myrm_agent_harness", 40.0),
        ("import myrm_agent_harness.agent.types", 70.0),
        ("from myrm_agent_harness import create_skill_agent", 50.0),
        ("import myrm_agent_harness.agent.security.types", 75.0),
        ("import myrm_agent_harness.agent.security.channel_presets", 55.0),
    ],
)
def test_public_import_hot_paths_are_fast(import_statement: str, threshold_ms: float) -> None:
    """Guard the fresh-process import paths against regressions."""
    median_ms = _measure_import_median_ms(import_statement)
    assert median_ms < threshold_ms, (
        f"{import_statement!r} median {median_ms:.2f}ms exceeds threshold {threshold_ms:.2f}ms"
    )
