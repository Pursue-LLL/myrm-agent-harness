"""Architecture gate: pytest helpers must not live under src/."""

from __future__ import annotations

from pathlib import Path

import pytest

HARNESS_ROOT = Path(__file__).resolve().parents[2]
LEGACY_TEST_SUPPORT = HARNESS_ROOT / "src" / "myrm_agent_harness" / "test_support"


@pytest.mark.architecture
def test_src_test_support_directory_must_not_exist() -> None:
    assert not LEGACY_TEST_SUPPORT.exists(), (
        "src/myrm_agent_harness/test_support/ must not exist; "
        "use tests/support/ for pytest-only helpers"
    )
