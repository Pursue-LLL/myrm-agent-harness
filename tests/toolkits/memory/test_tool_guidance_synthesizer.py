"""Unit tests for pure-functional Tool Guidance synthesizer and contracts.

Verifies:
1. Probe command detection (prevents false-positive negative rules).
2. Environment fingerprint isolation (Darwin vs Linux sandbox isolation).
3. Max 3 guidelines per tool bounded capacity.
4. Alphabetical cache-stable output order.
5. Pinned rules precedence.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.tool_guidance_synthesizer import (
    is_exploratory_probe,
    synthesize_tool_guidance,
)
from myrm_agent_harness.toolkits.memory.tool_guidance_types import ToolGuidanceItem


def test_probe_command_detection() -> None:
    assert is_exploratory_probe("command -v rustc") is True
    assert is_exploratory_probe("which gcc") is True
    assert is_exploratory_probe("type -p python3") is True
    assert is_exploratory_probe("grep -q 'pattern' file.txt") is True
    assert is_exploratory_probe("test -f /tmp/lock") is True
    assert is_exploratory_probe("[ -d /var/run ]") is True

    assert is_exploratory_probe("sed -i 's/foo/bar/' file.txt") is False
    assert is_exploratory_probe("npm run build") is False
    assert is_exploratory_probe(None) is False
    assert is_exploratory_probe("") is False


def test_environment_fingerprint_isolation() -> None:
    items = [
        ToolGuidanceItem(
            id="g1",
            tool_name="bash_code_execute_tool",
            rule_text="On macOS sed -i requires empty string ''",
            trigger_pattern="sed -i 's/a/b/'",
            env_fingerprint="os:darwin",
        ),
        ToolGuidanceItem(
            id="g2",
            tool_name="bash_code_execute_tool",
            rule_text="On Linux sed -i does not take empty string argument",
            trigger_pattern="sed -i '' 's/a/b/'",
            env_fingerprint="os:linux",
        ),
        ToolGuidanceItem(
            id="g3",
            tool_name="bash_code_execute_tool",
            rule_text="Always run pytest with --tb=short",
            trigger_pattern="pytest",
            env_fingerprint=None,  # global
        ),
    ]

    # In darwin environment, g2 should be omitted, g1 and g3 present
    darwin_res = synthesize_tool_guidance(items, current_env="os:darwin")
    assert "bash_code_execute_tool" in darwin_res
    rules_darwin = darwin_res["bash_code_execute_tool"]
    assert any("macOS sed" in r for r in rules_darwin)
    assert not any("Linux sed" in r for r in rules_darwin)
    assert any("pytest" in r for r in rules_darwin)

    # In linux environment, g1 should be omitted, g2 and g3 present
    linux_res = synthesize_tool_guidance(items, current_env="os:linux")
    rules_linux = linux_res["bash_code_execute_tool"]
    assert any("Linux sed" in r for r in rules_linux)
    assert not any("macOS sed" in r for r in rules_linux)
    assert any("pytest" in r for r in rules_linux)


def test_max_three_guidelines_and_cache_stable_ordering() -> None:
    items = [
        ToolGuidanceItem(
            id=f"g-{i}",
            tool_name="web_fetch_tool",
            rule_text=f"Rule {i}: Always specify scheme",
            trigger_pattern=f"fetch {i}",
            confidence=float(i),
            is_pinned=(i == 1),  # Rule 1 is pinned
        )
        for i in range(6)
    ]

    res = synthesize_tool_guidance(items, target_tools={"web_fetch_tool"})
    guidelines = res["web_fetch_tool"]

    # Maximum 3 guidelines per tool
    assert len(guidelines) == 3

    # Pinned rule 1 must be included
    assert any("Rule 1:" in r for r in guidelines)

    # Output list must be alphabetically sorted for deterministic Prompt Cache stability
    assert guidelines == sorted(guidelines)


def test_target_tools_filtering() -> None:
    items = [
        ToolGuidanceItem(
            id="g-bash",
            tool_name="bash_code_execute_tool",
            rule_text="Do not use sudo in sandbox",
            trigger_pattern="sudo",
        ),
        ToolGuidanceItem(
            id="g-fetch",
            tool_name="web_fetch_tool",
            rule_text="Use timeout parameter",
            trigger_pattern="fetch",
        ),
    ]

    # If only web_fetch_tool is in active request tools, bash guidance is excluded
    res = synthesize_tool_guidance(items, target_tools={"web_fetch_tool"})
    assert "web_fetch_tool" in res
    assert "bash_code_execute_tool" not in res
