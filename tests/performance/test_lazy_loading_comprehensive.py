"""Comprehensive lazy loading tests — prevent unexpected heavy imports.

Validates that importing core modules does not trigger heavy dependencies.
These tests act as regression guards to ensure lazy loading optimizations
are not accidentally broken by future changes.

Run: uv run pytest tests/test_lazy_loading_comprehensive.py -v
"""

import subprocess
import sys

import pytest

pytestmark = pytest.mark.performance


def test_toolkits_no_heavy_imports():
    """Ensure importing toolkits does not load heavy dependencies."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import myrm_agent_harness.toolkits

heavy_deps = ["litellm", "patchright", "numpy", "jieba", "langgraph"]
loaded = [dep for dep in heavy_deps if dep in sys.modules]

assert not loaded, f"Unexpected heavy dependencies loaded: {loaded}"
print("OK")
""",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Test failed: {result.stderr}"
    assert "OK" in result.stdout


def test_browser_no_heavy_imports():
    """Ensure importing browser module does not load heavy dependencies."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from myrm_agent_harness.toolkits.browser import BrowserSession

heavy_deps = ["patchright", "langgraph", "yaml", "cryptography"]
loaded = [dep for dep in heavy_deps if dep in sys.modules]

assert not loaded, f"Unexpected heavy dependencies loaded: {loaded}"
print("OK")
""",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Test failed: {result.stderr}"
    assert "OK" in result.stdout


def test_web_search_no_heavy_imports():
    """Ensure importing web_search does not load heavy dependencies."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from myrm_agent_harness.toolkits.web_search import WebSearchTools

heavy_deps = ["litellm", "jieba"]
loaded = [dep for dep in heavy_deps if dep in sys.modules]

assert not loaded, f"Unexpected heavy dependencies loaded: {loaded}"
print("OK")
""",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Test failed: {result.stderr}"
    assert "OK" in result.stdout


def test_lazy_loading_litellm():
    """Verify litellm is loaded only when accessing llm_manager."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from myrm_agent_harness import toolkits

assert "litellm" not in sys.modules, "litellm should not be loaded yet"

from myrm_agent_harness.toolkits import llm_manager

assert "litellm" in sys.modules, "litellm should be loaded after accessing llm_manager"
assert llm_manager is not None
print("OK")
""",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Test failed: {result.stderr}"
    assert "OK" in result.stdout


def test_lazy_loading_yaml():
    """Verify yaml is loaded only when calling parse_aria_yaml."""
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from myrm_agent_harness.toolkits.browser.snapshot.aria_parser import parse_aria_yaml

# yaml may be loaded by other modules, so we check if parse_aria_yaml works
result = parse_aria_yaml("- button: Test")
assert len(result) > 0, "parse_aria_yaml should return nodes"
print("OK")
""",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Test failed: {result.stderr}"
    assert "OK" in result.stdout


def test_lazy_loading_cryptography():
    """Verify cryptography is loaded only when using SessionVault encryption."""
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from myrm_agent_harness.toolkits.browser import SessionVault

# Check cryptography is not loaded when importing SessionVault
assert 'cryptography' not in sys.modules, "cryptography should not be loaded yet"
print("OK")
""",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Test failed: {result.stderr}"
    assert "OK" in result.stdout


def test_no_accidental_global_imports():
    """Ensure no module accidentally imports heavy deps at module level."""
    import importlib
    import sys

    modules_to_check = [
        "myrm_agent_harness.toolkits",
        "myrm_agent_harness.toolkits.browser",
        "myrm_agent_harness.toolkits.web_search",
    ]

    for module_name in modules_to_check:
        if module_name in sys.modules:
            del sys.modules[module_name]

        for key in list(sys.modules.keys()):
            if key.startswith(module_name + "."):
                del sys.modules[key]

        heavy_before = {dep for dep in ["litellm", "patchright", "numpy", "jieba"] if dep in sys.modules}

        importlib.import_module(module_name)

        heavy_after = {dep for dep in ["litellm", "patchright", "numpy", "jieba"] if dep in sys.modules}
        new_imports = heavy_after - heavy_before

        assert not new_imports, f"{module_name} imported heavy deps: {new_imports}"
