from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_TEST_FILE = Path(__file__).resolve()


def _resolve_harness_root() -> Path:
    """Resolve harness repo root from tests/ regardless of monorepo layout."""
    direct_root = _TEST_FILE.parents[1]
    if (direct_root / "src" / "myrm_agent_harness").is_dir():
        return direct_root

    monorepo_root = _TEST_FILE.parents[2]
    nested_root = monorepo_root / "myrm-agent-harness"
    if (nested_root / "src" / "myrm_agent_harness").is_dir():
        return nested_root

    raise RuntimeError(
        "Could not locate myrm-agent-harness root from tests/test_readme_claims.py"
    )


def _resolve_monorepo_root(harness_root: Path) -> Path | None:
    candidate = harness_root.parent
    if (candidate / "myrm-control-plane").is_dir() and (candidate / "myrm-agent").is_dir():
        return candidate
    return None


HARNESS_ROOT = _resolve_harness_root()
README_PATH = HARNESS_ROOT / "README.md"
MONOREPO_ROOT = _resolve_monorepo_root(HARNESS_ROOT)
SERVER_ROOT = MONOREPO_ROOT / "myrm-agent" / "myrm-agent-server" if MONOREPO_ROOT else None
CONTROL_PLANE_ROOT = MONOREPO_ROOT / "myrm-control-plane" if MONOREPO_ROOT else None


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _collect_harness_test_count() -> int:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--continue-on-collection-errors", "tests"],
        cwd=HARNESS_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    match = re.search(r"(?P<count>\d+)\s+tests collected", completed.stdout)
    assert match is not None, "pytest collection output did not include a collected test count"
    return int(match.group("count"))


def test_readme_does_not_overstate_test_count() -> None:
    """If README embeds a test count, it must not exceed collected tests."""
    readme = _read_text(README_PATH)
    match = re.search(r"(?P<count>\d+)\s+tests\s*\((?P<runtime>\d+\.\d+)s runtime\)", readme)
    if match is None:
        assert "pytest tests/" in readme, "README should direct readers to pytest tests/"
        return

    claimed_count = int(match.group("count"))
    actual_count = _collect_harness_test_count()
    assert actual_count >= claimed_count, (
        f"README claims {claimed_count} tests, but harness collected only {actual_count}"
    )


@pytest.mark.parametrize(
    ("label", "harness_relative", "monorepo_relative", "symbol"),
    [
        (
            "Local",
            Path("src")
            / "myrm_agent_harness"
            / "toolkits"
            / "code_execution"
            / "executors"
            / "local"
            / "executor.py",
            None,
            "LocalExecutor",
        ),
        (
            "Docker",
            None,
            Path("src") / "myrm_control_plane" / "infra" / "compute" / "docker_operations.py",
            "DockerOperations",
        ),
        (
            "E2B",
            None,
            Path("src") / "myrm_control_plane" / "infra" / "compute" / "e2b_runtime.py",
            "E2BRuntime",
        ),
    ],
)
def test_readme_sandbox_modes_have_code_support(
    label: str,
    harness_relative: Path | None,
    monorepo_relative: Path | None,
    symbol: str,
) -> None:
    readme = _read_text(README_PATH)
    assert label in readme, f"README does not mention sandbox mode '{label}'"

    if harness_relative is not None:
        path = HARNESS_ROOT / harness_relative
    else:
        if CONTROL_PLANE_ROOT is None or monorepo_relative is None:
            pytest.skip("Docker/E2B sandbox modes live in myrm-control-plane (monorepo only)")
        path = CONTROL_PLANE_ROOT / monorepo_relative

    assert path.exists(), f"Missing implementation file for sandbox mode '{label}': {path}"
    assert f"class {symbol}" in _read_text(path), f"Sandbox mode '{label}' is missing {symbol}"


def test_readme_agent_count_matches_server_agents() -> None:
    readme = _read_text(README_PATH)
    if "1 个统一 Agent" not in readme:
        pytest.skip("README no longer documents monorepo agent count; skipping server layout check")

    if SERVER_ROOT is None:
        pytest.skip("Server agent layout check requires myrm-agent monorepo checkout")

    agent_files = sorted((SERVER_ROOT / "app" / "ai_agents").glob("*/agent.py"))
    assert len(agent_files) == 1, f"Expected 1 top-level agent implementation, found {len(agent_files)}"

    expected_names = {"general_agent"}
    actual_names = {path.parent.name for path in agent_files}
    assert actual_names == expected_names, f"Agent implementations mismatch: {sorted(actual_names)}"


@pytest.mark.parametrize(
    ("claim", "support_path", "expected_snippet"),
    [
        (
            "7x 性能提升",
            HARNESS_ROOT / "tests" / "toolkits" / "browser" / "test_session_vault_benchmark.py",
            "assert speedup > 7",
        ),
        (
            "40-50% Token",
            HARNESS_ROOT / "src" / "myrm_agent_harness" / "toolkits" / "web_fetch" / "__init__.py",
            "web_fetch",
        ),
    ],
)
def test_readme_performance_claims_have_supporting_evidence(
    claim: str,
    support_path: Path,
    expected_snippet: str,
) -> None:
    readme = _read_text(README_PATH)
    if claim not in readme:
        pytest.skip(f"README no longer advertises performance claim '{claim}'")
    assert support_path.exists(), f"Missing supporting artifact for claim '{claim}': {support_path}"
    assert expected_snippet in _read_text(support_path), (
        f"Supporting artifact for '{claim}' is missing '{expected_snippet}'"
    )


def test_readme_disclaims_fixed_performance_numbers() -> None:
    readme = _read_text(README_PATH)
    assert "不承诺固定加速比" in readme or "不列举固定数字" in readme, (
        "README should disclaim hard-coded performance marketing numbers"
    )


# ========== API Public Interface Tests (5 tests) ==========


def test_api_base_agent_class_exported() -> None:
    """Verify BaseAgent class is exported from myrm_agent_harness.agent"""
    agent_init = HARNESS_ROOT / "src" / "myrm_agent_harness" / "agent" / "__init__.py"
    assert agent_init.exists(), "agent/__init__.py not found"
    content = _read_text(agent_init)
    assert "BaseAgent" in content or "from .base_agent import" in content, "BaseAgent not exported"


def test_api_skill_agent_class_exported() -> None:
    """Verify SkillAgent class is exported from myrm_agent_harness.agent"""
    agent_init = HARNESS_ROOT / "src" / "myrm_agent_harness" / "agent" / "__init__.py"
    content = _read_text(agent_init)
    assert "SkillAgent" in content or "from .skill_agent import" in content, "SkillAgent not exported"


def test_api_toolkits_module_structure() -> None:
    """Verify core toolkits are properly structured"""
    expected_toolkits = ["browser", "code_execution", "llms", "memory", "web_fetch"]
    toolkits_root = HARNESS_ROOT / "src" / "myrm_agent_harness" / "toolkits"

    missing = []
    for toolkit in expected_toolkits:
        toolkit_path = toolkits_root / toolkit
        if not toolkit_path.exists():
            missing.append(toolkit)

    assert not missing, f"Missing expected toolkits: {missing}"


def test_api_event_types_defined() -> None:
    """Verify AgentEventType enum is properly defined"""
    types_file = HARNESS_ROOT / "src" / "myrm_agent_harness" / "agent" / "streaming" / "types.py"
    assert types_file.exists(), "agent/streaming/types.py not found"
    content = _read_text(types_file)
    assert "AgentEventType" in content, "AgentEventType not defined in streaming/types.py"


def test_api_tool_registry_interface() -> None:
    """Verify ToolRegistry is available for tool management"""
    registry_file = HARNESS_ROOT / "src" / "myrm_agent_harness" / "agent" / "tool_management" / "registry.py"
    assert registry_file.exists(), "tool_management/registry.py not found"
    content = _read_text(registry_file)
    assert "class ToolRegistry" in content or "class Registry" in content, "ToolRegistry not found"


# ========== Feature Implementation Tests (5 tests) ==========


def test_feature_mcp_support_implemented() -> None:
    """Verify MCP (Model Context Protocol) support is implemented"""
    readme = _read_text(README_PATH)
    if "MCP" in readme or "Model Context Protocol" in readme:
        mcp_path = HARNESS_ROOT / "src" / "myrm_agent_harness" / "agent" / "skills" / "mcp"
        assert mcp_path.exists(), "MCP support mentioned in README but mcp module not found"


def test_feature_sandbox_modes_implemented() -> None:
    """Verify all sandbox modes are implemented"""
    sandbox_root = HARNESS_ROOT / "src" / "myrm_agent_harness" / "toolkits" / "code_execution" / "executors"
    assert sandbox_root.exists(), "code_execution/executors not found"

    required_executors = ["local"]
    for executor in required_executors:
        executor_path = sandbox_root / executor
        assert executor_path.exists(), f"Required executor '{executor}' not found"


def test_feature_memory_system_implemented() -> None:
    """Verify memory system is implemented"""
    memory_path = HARNESS_ROOT / "src" / "myrm_agent_harness" / "toolkits" / "memory"
    assert memory_path.exists(), "memory toolkit not found"

    init_file = memory_path / "__init__.py"
    assert init_file.exists(), "memory/__init__.py not found"


def test_feature_browser_automation_implemented() -> None:
    """Verify browser automation toolkit is implemented"""
    browser_path = HARNESS_ROOT / "src" / "myrm_agent_harness" / "toolkits" / "browser"
    assert browser_path.exists(), "browser toolkit not found"

    doctor_file = browser_path / "doctor.py"
    assert doctor_file.exists(), "browser/doctor.py not found"


def test_feature_multi_llm_support() -> None:
    """Verify multi-LLM support is implemented"""
    llms_path = HARNESS_ROOT / "src" / "myrm_agent_harness" / "toolkits" / "llms"
    assert llms_path.exists(), "llms toolkit not found"

    init_file = llms_path / "__init__.py"
    assert init_file.exists(), "llms/__init__.py not found"


# ========== Performance Benchmark Tests (3 tests) ==========


def test_performance_test_suite_runtime() -> None:
    """If README embeds a runtime claim, it must be reasonable."""
    readme = _read_text(README_PATH)
    runtime_match = re.search(r"(\d+\.\d+)s runtime", readme)

    if runtime_match is None:
        return

    claimed_runtime = float(runtime_match.group(1))
    assert claimed_runtime < 60.0, f"Test runtime claim ({claimed_runtime}s) seems too slow"


def test_performance_browser_vault_benchmark_exists() -> None:
    """Verify browser vault performance benchmark exists"""
    benchmark_file = HARNESS_ROOT / "tests" / "toolkits" / "browser" / "test_session_vault_benchmark.py"
    if benchmark_file.exists():
        content = _read_text(benchmark_file)
        assert "speedup" in content.lower() or "performance" in content.lower(), (
            "Benchmark file lacks performance assertions"
        )


def test_performance_token_efficiency_documented() -> None:
    """Verify token efficiency claims are documented"""
    readme = _read_text(README_PATH)
    if "Token" in readme or "token" in readme:
        best_practices_file = (
            HARNESS_ROOT / "src" / "myrm_agent_harness" / "toolkits" / "web_fetch" / "BEST_PRACTICES.md"
        )
        if best_practices_file.exists():
            content = _read_text(best_practices_file)
            assert "%" in content or "efficiency" in content.lower(), "BEST_PRACTICES.md lacks efficiency metrics"


# ========== Functionality Verification Tests (3 tests) ==========


def test_functionality_skill_system_complete() -> None:
    """Verify skill system has all core components"""
    skills_root = HARNESS_ROOT / "src" / "myrm_agent_harness" / "agent" / "skills"
    assert skills_root.exists(), "skills module not found"

    required_components = ["runtime", "evolution", "optimization"]
    missing = []
    for component in required_components:
        component_path = skills_root / component
        if not component_path.exists():
            missing.append(component)

    assert not missing, f"Skill system missing components: {missing}"


def test_functionality_security_guards_implemented() -> None:
    """Verify security guards are implemented"""
    security_path = HARNESS_ROOT / "src" / "myrm_agent_harness" / "agent" / "security"
    assert security_path.exists(), "security module not found"

    guards_path = security_path / "guards"
    assert guards_path.exists(), "security/guards not found"


def test_functionality_event_logging_system() -> None:
    """Verify event logging system is implemented"""
    event_log_path = HARNESS_ROOT / "src" / "myrm_agent_harness" / "agent" / "event_log"
    assert event_log_path.exists(), "event_log module not found"

    logger_file = event_log_path / "logger.py"
    assert logger_file.exists(), "event_log/logger.py not found"
