"""Environment dependency specifications and tool surface correlation engine.

Declares required host/sandbox runtime dependencies (system binaries, Python packages,
OS capabilities) for Action Tools, providing forward inspection and reverse impact analysis.

[INPUT]
- .tool_layers::ToolLayer, _TOOL_LAYERS (POS: Tool action space SSOT)
- .types::ToolSnapshot (POS: Tool metadata for API inspection)

[OUTPUT]
- DependencyKind: Enum (SYSTEM_BINARY, PYTHON_PACKAGE, RUNTIME_FEATURE, OS_CAPABILITY)
- RequirementLevel: Enum (HARD_REQUIRED, SOFT_OPTIONAL)
- EnvDependencySpec: Dataclass declaring a single environmental requirement
- ToolEnvDependencyProfile: Dataclass grouping dependencies for a single tool
- TOOL_ENV_DEPENDENCY_REGISTRY: SSOT mapping tool_name -> ToolEnvDependencyProfile
- get_tool_env_dependencies(): Query dependencies for a tool
- get_tools_requiring_dependency(): Reverse index query
- probe_tool_environment(): Probe live host system against tool requirements
- correlate_tool_surface_env_health(): Complete matrix check for all tools

[POS]
Harness framework layer SSOT for tool environment dependency governance.
Used by Desktop setup wizard, Cloud Sandbox provisioning, and CI architecture gates.
"""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable


class DependencyKind(StrEnum):
    """Classification of environment dependency."""

    SYSTEM_BINARY = "system_binary"
    PYTHON_PACKAGE = "python_package"
    RUNTIME_FEATURE = "runtime_feature"
    OS_CAPABILITY = "os_capability"


class RequirementLevel(StrEnum):
    """Whether tool fails completely without this dependency or falls back gracefully."""

    HARD_REQUIRED = "hard_required"
    SOFT_OPTIONAL = "soft_optional"


@dataclass(frozen=True, slots=True)
class EnvDependencySpec:
    """Specification of a single environment dependency requirement."""

    name: str
    kind: DependencyKind
    level: RequirementLevel = RequirementLevel.HARD_REQUIRED
    min_version: str | None = None
    probe_command: str | None = None
    description: str = ""
    fallback_strategy: str | None = None


@dataclass(frozen=True, slots=True)
class ToolEnvDependencyProfile:
    """Environment dependencies required/optional for a specific Action Tool."""

    tool_name: str
    dependencies: tuple[EnvDependencySpec, ...] = field(default_factory=tuple)

    @property
    def has_dependencies(self) -> bool:
        return len(self.dependencies) > 0

    @property
    def hard_requirements(self) -> list[EnvDependencySpec]:
        return [dep for dep in self.dependencies if dep.level == RequirementLevel.HARD_REQUIRED]

    @property
    def soft_requirements(self) -> list[EnvDependencySpec]:
        return [dep for dep in self.dependencies if dep.level == RequirementLevel.SOFT_OPTIONAL]


@dataclass(frozen=True, slots=True)
class DependencyProbeResult:
    """Result of probing an environment dependency."""

    spec: EnvDependencySpec
    satisfied: bool
    detected_version: str | None = None
    probe_error: str | None = None


@dataclass(frozen=True, slots=True)
class ToolEnvHealthReport:
    """Health status of a tool's execution environment."""

    tool_name: str
    is_fully_satisfied: bool
    is_operational: bool  # True if all HARD_REQUIRED dependencies are satisfied
    results: list[DependencyProbeResult] = field(default_factory=list)
    missing_hard: list[str] = field(default_factory=list)
    missing_soft: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SSOT: Canonical Environment Dependencies for Harness Action Tools
# ---------------------------------------------------------------------------

_CORE_BASH_DEPS = (
    EnvDependencySpec(
        name="sh",
        kind=DependencyKind.SYSTEM_BINARY,
        level=RequirementLevel.HARD_REQUIRED,
        description="Standard POSIX shell binary (or bash/zsh on Unix, powershell/cmd on Windows)",
    ),
)

_CORE_FILE_SEARCH_DEPS = (
    EnvDependencySpec(
        name="rg",
        kind=DependencyKind.SYSTEM_BINARY,
        level=RequirementLevel.SOFT_OPTIONAL,
        description="Ripgrep high-performance regex search binary (fallback to Python re grep)",
        fallback_strategy="Python stdlib re and os.walk fallback",
    ),
)

_BROWSER_DEPS = (
    EnvDependencySpec(
        name="patchright",
        kind=DependencyKind.PYTHON_PACKAGE,
        level=RequirementLevel.HARD_REQUIRED,
        description="Patchright / Playwright browser automation driver",
    ),
)

_DESKTOP_DEPS = (
    EnvDependencySpec(
        name="pyautogui",
        kind=DependencyKind.PYTHON_PACKAGE,
        level=RequirementLevel.HARD_REQUIRED,
        description="Cross-platform GUI automation and mouse/keyboard controller",
    ),
    EnvDependencySpec(
        name="pillow",
        kind=DependencyKind.PYTHON_PACKAGE,
        level=RequirementLevel.HARD_REQUIRED,
        description="Python Imaging Library (PIL Fork) for screen capture processing",
    ),
)

_VIDEO_TOOL_DEPS = (
    EnvDependencySpec(
        name="ffmpeg",
        kind=DependencyKind.SYSTEM_BINARY,
        level=RequirementLevel.SOFT_OPTIONAL,
        description="FFmpeg audio/video processing suite",
        fallback_strategy="Remote API / Cloud rendering fallback",
    ),
)


# Canonical registry mapping tool name -> ToolEnvDependencyProfile
TOOL_ENV_DEPENDENCY_REGISTRY: dict[str, ToolEnvDependencyProfile] = {
    # Shell / Code Execution
    "bash_code_execute_tool": ToolEnvDependencyProfile(
        tool_name="bash_code_execute_tool",
        dependencies=_CORE_BASH_DEPS,
    ),
    "bash_process_tool": ToolEnvDependencyProfile(
        tool_name="bash_process_tool",
        dependencies=_CORE_BASH_DEPS,
    ),
    # Core search optimizations
    "grep_tool": ToolEnvDependencyProfile(
        tool_name="grep_tool",
        dependencies=_CORE_FILE_SEARCH_DEPS,
    ),
    # Browser tools
    "browser_navigate_tool": ToolEnvDependencyProfile(tool_name="browser_navigate_tool", dependencies=_BROWSER_DEPS),
    "browser_interact_tool": ToolEnvDependencyProfile(tool_name="browser_interact_tool", dependencies=_BROWSER_DEPS),
    "browser_manage_tool": ToolEnvDependencyProfile(tool_name="browser_manage_tool", dependencies=_BROWSER_DEPS),
    "browser_inspect_tool": ToolEnvDependencyProfile(tool_name="browser_inspect_tool", dependencies=_BROWSER_DEPS),
    "browser_snapshot_tool": ToolEnvDependencyProfile(tool_name="browser_snapshot_tool", dependencies=_BROWSER_DEPS),
    "browser_extract_tool": ToolEnvDependencyProfile(tool_name="browser_extract_tool", dependencies=_BROWSER_DEPS),
    "browser_execute_script_tool": ToolEnvDependencyProfile(
        tool_name="browser_execute_script_tool", dependencies=_BROWSER_DEPS
    ),
    # Desktop automation
    "desktop_snapshot_tool": ToolEnvDependencyProfile(tool_name="desktop_snapshot_tool", dependencies=_DESKTOP_DEPS),
    "desktop_interact_tool": ToolEnvDependencyProfile(tool_name="desktop_interact_tool", dependencies=_DESKTOP_DEPS),
    "desktop_vision_tool": ToolEnvDependencyProfile(tool_name="desktop_vision_tool", dependencies=_DESKTOP_DEPS),
    # Media generation & processing (when enabled in runtime)
}


def get_tool_env_dependencies(tool_name: str) -> ToolEnvDependencyProfile:
    """Retrieve declared environment dependencies for a given tool name."""
    return TOOL_ENV_DEPENDENCY_REGISTRY.get(
        tool_name,
        ToolEnvDependencyProfile(tool_name=tool_name, dependencies=()),
    )


def get_tools_requiring_dependency(dependency_name: str) -> list[str]:
    """Reverse index lookup: find all tool names requiring a specific dependency."""
    matched: list[str] = []
    for tool_name, profile in TOOL_ENV_DEPENDENCY_REGISTRY.items():
        if any(dep.name.lower() == dependency_name.lower() for dep in profile.dependencies):
            matched.append(tool_name)
    return sorted(matched)


def probe_dependency_satisfaction(spec: EnvDependencySpec) -> DependencyProbeResult:
    """Check whether a single environmental dependency is satisfied in current runtime."""
    try:
        if spec.kind == DependencyKind.SYSTEM_BINARY:
            # Check PATH executable
            found_path = shutil.which(spec.name)
            if found_path is not None:
                return DependencyProbeResult(spec=spec, satisfied=True, detected_version=found_path)
            # Special case for shell on Windows
            if spec.name in ("sh", "bash"):
                if shutil.which("powershell") or shutil.which("cmd") or shutil.which("pwsh"):
                    return DependencyProbeResult(spec=spec, satisfied=True, detected_version="windows_shell")
            return DependencyProbeResult(spec=spec, satisfied=False, probe_error=f"Binary '{spec.name}' not found on PATH")

        if spec.kind == DependencyKind.PYTHON_PACKAGE:
            # Check Python import availability
            spec_module = importlib.util.find_spec(spec.name)
            if spec_module is not None:
                return DependencyProbeResult(spec=spec, satisfied=True)
            return DependencyProbeResult(
                spec=spec, satisfied=False, probe_error=f"Python module '{spec.name}' not importable"
            )

        # Fallback default for runtime/OS capability
        return DependencyProbeResult(spec=spec, satisfied=True)
    except Exception as exc:
        return DependencyProbeResult(spec=spec, satisfied=False, probe_error=str(exc))


def probe_tool_env_health(tool_name: str) -> ToolEnvHealthReport:
    """Probe live runtime health for a single tool."""
    profile = get_tool_env_dependencies(tool_name)
    results: list[DependencyProbeResult] = []
    missing_hard: list[str] = []
    missing_soft: list[str] = []

    for dep in profile.dependencies:
        res = probe_dependency_satisfaction(dep)
        results.append(res)
        if not res.satisfied:
            if dep.level == RequirementLevel.HARD_REQUIRED:
                missing_hard.append(dep.name)
            else:
                missing_soft.append(dep.name)

    is_operational = len(missing_hard) == 0
    is_fully_satisfied = is_operational and len(missing_soft) == 0

    return ToolEnvHealthReport(
        tool_name=tool_name,
        is_fully_satisfied=is_fully_satisfied,
        is_operational=is_operational,
        results=results,
        missing_hard=missing_hard,
        missing_soft=missing_soft,
    )


def correlate_tool_surface_env_health(tool_names: Iterable[str] | None = None) -> dict[str, ToolEnvHealthReport]:
    """Generate complete environment health correlation matrix for specified or all registered tools."""
    from myrm_agent_harness.agent.tool_management.tool_layers import _TOOL_LAYERS

    target_tools = set(tool_names) if tool_names is not None else set(_TOOL_LAYERS.keys())
    matrix: dict[str, ToolEnvHealthReport] = {}
    for name in sorted(target_tools):
        matrix[name] = probe_tool_env_health(name)
    return matrix


def export_env_dependency_inventory() -> list[dict[str, Any]]:
    """Export deterministic JSON-serializable inventory for CI audit and documentation."""
    items: list[dict[str, Any]] = []
    for tool_name in sorted(TOOL_ENV_DEPENDENCY_REGISTRY.keys()):
        profile = TOOL_ENV_DEPENDENCY_REGISTRY[tool_name]
        items.append({
            "tool_name": tool_name,
            "dependencies": [
                {
                    "name": dep.name,
                    "kind": dep.kind.value,
                    "level": dep.level.value,
                    "description": dep.description,
                    "fallback_strategy": dep.fallback_strategy,
                }
                for dep in profile.dependencies
            ],
        })
    return items
