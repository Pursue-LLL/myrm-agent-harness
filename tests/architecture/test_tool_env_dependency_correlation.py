"""Architecture gate: Tool surface environment dependency correlation test.

Asserts that:
1. All Action tools declared in TOOL_ENV_DEPENDENCY_REGISTRY exist in _TOOL_LAYERS.
2. Forward dependencies and reverse dependency indexing are symmetrical and consistent.
3. Probing functions handle both present and missing dependencies gracefully without raising unhandled exceptions.
4. Exported environment inventory adheres to deterministic schema specifications.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from myrm_agent_harness.agent.tool_management.env_dependency import (
    TOOL_ENV_DEPENDENCY_REGISTRY,
    DependencyKind,
    EnvDependencySpec,
    RequirementLevel,
    correlate_tool_surface_env_health,
    export_env_dependency_inventory,
    get_tools_requiring_dependency,
    probe_dependency_satisfaction,
    probe_tool_env_health,
)
from myrm_agent_harness.agent.tool_management.tool_catalog import (
    get_tool_env_profile,
    probe_tool_runtime_health,
)
from myrm_agent_harness.agent.tool_management.tool_layers import _TOOL_LAYERS


@pytest.mark.architecture
def test_all_env_dependent_tools_are_registered_action_tools() -> None:
    """Ensure no orphan tool names exist in TOOL_ENV_DEPENDENCY_REGISTRY."""
    registered_tools = set(_TOOL_LAYERS.keys())
    for tool_name in TOOL_ENV_DEPENDENCY_REGISTRY:
        assert (
            tool_name in registered_tools
        ), f"Tool '{tool_name}' in TOOL_ENV_DEPENDENCY_REGISTRY is not in _TOOL_LAYERS"


@pytest.mark.architecture
def test_reverse_dependency_lookup_symmetry() -> None:
    """Verify that get_tools_requiring_dependency returns exact tools declared with that dependency."""
    # Test reverse lookup for 'patchright'
    browser_tools = get_tools_requiring_dependency("patchright")
    assert "browser_navigate_tool" in browser_tools
    assert "browser_interact_tool" in browser_tools
    assert "bash_code_execute_tool" not in browser_tools

    # Test reverse lookup for 'sh'
    sh_tools = get_tools_requiring_dependency("sh")
    assert "bash_code_execute_tool" in sh_tools
    assert "bash_process_tool" in sh_tools
    assert "grep_tool" not in sh_tools


@pytest.mark.architecture
def test_probe_dependency_and_tool_health() -> None:
    """Test live probe behavior across various specs."""
    # Probing standard POSIX / windows shell
    shell_spec = EnvDependencySpec(name="sh", kind=DependencyKind.SYSTEM_BINARY)
    res = probe_dependency_satisfaction(shell_spec)
    assert res.satisfied is True or res.detected_version is not None

    # Probing non-existent system binary
    bogus_binary_spec = EnvDependencySpec(
        name="non_existent_binary_xyz_123",
        kind=DependencyKind.SYSTEM_BINARY,
    )
    res_bogus = probe_dependency_satisfaction(bogus_binary_spec)
    assert res_bogus.satisfied is False
    assert res_bogus.probe_error is not None

    # Probing non-existent python module
    bogus_pkg_spec = EnvDependencySpec(
        name="non_existent_python_pkg_xyz_123",
        kind=DependencyKind.PYTHON_PACKAGE,
    )
    res_pkg = probe_dependency_satisfaction(bogus_pkg_spec)
    assert res_pkg.satisfied is False
    assert "not importable" in (res_pkg.probe_error or "")

    # Tool health report for bash_code_execute_tool
    report = probe_tool_env_health("bash_code_execute_tool")
    assert report.tool_name == "bash_code_execute_tool"
    assert report.is_operational is True

    # Catalog wrapper verification
    catalog_profile = get_tool_env_profile("bash_code_execute_tool")
    assert catalog_profile.tool_name == "bash_code_execute_tool"
    catalog_report = probe_tool_runtime_health("bash_code_execute_tool")
    assert catalog_report.is_operational is True


@pytest.mark.architecture
def test_correlate_tool_surface_env_health_matrix() -> None:
    """Verify matrix calculation over all tools."""
    matrix = correlate_tool_surface_env_health(["bash_code_execute_tool", "grep_tool"])
    assert "bash_code_execute_tool" in matrix
    assert "grep_tool" in matrix
    assert matrix["bash_code_execute_tool"].is_operational is True


@pytest.mark.architecture
def test_export_env_dependency_inventory_schema() -> None:
    """Validate exported inventory format."""
    inventory = export_env_dependency_inventory()
    assert isinstance(inventory, list)
    assert len(inventory) > 0

    for item in inventory:
        assert "tool_name" in item
        assert "dependencies" in item
        for dep in item["dependencies"]:
            assert "name" in dep
            assert "kind" in dep
            assert "level" in dep
            assert dep["level"] in (RequirementLevel.HARD_REQUIRED.value, RequirementLevel.SOFT_OPTIONAL.value)
