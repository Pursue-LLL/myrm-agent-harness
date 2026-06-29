"""Architecture gate: LLM media understanding belongs under toolkits/llms/, not top-level."""

from __future__ import annotations

from pathlib import Path

import pytest

HARNESS_ROOT = Path(__file__).resolve().parents[2]
TOOLKITS_ROOT = HARNESS_ROOT / "src" / "myrm_agent_harness" / "toolkits"
LLMS_VISION_ROOT = TOOLKITS_ROOT / "llms" / "vision"


@pytest.mark.architecture
def test_vision_package_lives_under_llms_not_toolkits_root() -> None:
    """Prevent regression: vision engines must stay in the llms media stack."""
    top_level_vision = TOOLKITS_ROOT / "vision"
    assert not top_level_vision.exists(), (
        f"{top_level_vision.relative_to(HARNESS_ROOT)} must not exist; "
        "use toolkits/llms/vision/ instead"
    )
    assert LLMS_VISION_ROOT.is_dir(), (
        f"{LLMS_VISION_ROOT.relative_to(HARNESS_ROOT)} must exist as the vision module root"
    )
    assert (LLMS_VISION_ROOT / "fallback_engine.py").is_file()
    assert (LLMS_VISION_ROOT / "video_analysis_engine.py").is_file()
