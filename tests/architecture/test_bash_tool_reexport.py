"""Architecture gate: bash_tool aggregate re-export integrity."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.architecture
def test_bash_tool_all_exports_are_importable() -> None:
    """Every name in bash_tool.__all__ must resolve on the public aggregate module."""
    mod = importlib.import_module("myrm_agent_harness.agent.meta_tools.bash.bash_tool")
    for name in mod.__all__:
        assert hasattr(mod, name), f"Missing bash_tool export: {name}"


@pytest.mark.architecture
def test_bash_tool_all_matches_public_surface() -> None:
    """__all__ must list exactly the supported public bash_tool symbols."""
    mod = importlib.import_module("myrm_agent_harness.agent.meta_tools.bash.bash_tool")
    expected = {
        "MAX_IMAGES_PER_RETURN",
        "BashInput",
        "create_bash_tool",
        "_build_background_listeners",
        "_classify_background_exit",
        "_format_result",
        "_get_os_hint",
        "_interpret_exit_code",
        "_maybe_build_image_blocks",
        "_restore_context_vars",
        "_track_context_access_in_command",
        "_truncate_bash_output",
    }
    assert set(mod.__all__) == expected
