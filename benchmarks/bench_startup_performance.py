"""Startup performance benchmark — measure module import times.

Validates lazy loading behavior:
- toolkits/__init__.py: llms, retriever, web_fetch 延迟导入
- browser/__init__.py: checkpoint, doctor 延迟导入
- web_search/__init__.py: LiteLLMSearch 延迟导入

Run: uv run pytest benchmarks/bench_startup_performance.py -v
"""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.benchmark(group="startup")
def test_import_myrm_agent_harness(benchmark):
    """Benchmark: import myrm_agent_harness"""

    def import_package():
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import time
start = time.time()
import myrm_agent_harness
print(f"{(time.time()-start)*1000:.2f}")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        return float(result.stdout.strip().split("\n")[-1])

    elapsed_ms = benchmark(import_package)
    assert elapsed_ms < 100, f"myrm_agent_harness import should be < 100ms, got {elapsed_ms:.2f}ms"


@pytest.mark.benchmark(group="startup")
def test_import_toolkits(benchmark):
    """Benchmark: import toolkits (litellm not loaded)"""

    def import_toolkits():
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import time
start = time.time()
from myrm_agent_harness import toolkits
print(f"{(time.time()-start)*1000:.2f}")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        return float(result.stdout.strip().split("\n")[-1])

    elapsed_ms = benchmark(import_toolkits)
    assert elapsed_ms < 150, f"toolkits import should be < 150ms, got {elapsed_ms:.2f}ms"


@pytest.mark.benchmark(group="startup")
def test_import_browser(benchmark):
    """Benchmark: import browser (patchright/langgraph not loaded)"""

    def import_browser():
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import time
start = time.time()
from myrm_agent_harness.toolkits.browser import BrowserSession
print(f"{(time.time()-start)*1000:.2f}")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        return float(result.stdout.strip().split("\n")[-1])

    elapsed_ms = benchmark(import_browser)
    assert elapsed_ms < 250, f"browser import should be < 250ms, got {elapsed_ms:.2f}ms"


@pytest.mark.benchmark(group="startup")
def test_import_web_search(benchmark):
    """Benchmark: import web_search (litellm not loaded)"""

    def import_web_search():
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import time
start = time.time()
from myrm_agent_harness.toolkits.web_search import WebSearchTools
print(f"{(time.time()-start)*1000:.2f}")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        return float(result.stdout.strip().split("\n")[-1])

    elapsed_ms = benchmark(import_web_search)
    assert elapsed_ms < 300, f"web_search import should be < 300ms, got {elapsed_ms:.2f}ms"


@pytest.mark.benchmark(group="lazy_loading")
def test_lazy_loading_litellm(benchmark):
    """Benchmark: litellm loads on first access"""

    def check_lazy_loading():
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import sys
from myrm_agent_harness import toolkits

# Should not load litellm
assert 'litellm' not in sys.modules, "litellm should not be loaded"

# Now access llm_manager (should trigger lazy load)
import time
start = time.time()
from myrm_agent_harness.toolkits import llm_manager
elapsed = (time.time()-start)*1000

assert 'litellm' in sys.modules, "litellm should be loaded now"
print(f"{elapsed:.2f}")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        if result.returncode != 0:
            raise AssertionError(f"Lazy loading check failed: {result.stderr}")
        return float(result.stdout.strip().split("\n")[-1])

    elapsed_ms = benchmark(check_lazy_loading)
    assert elapsed_ms < 5000, f"litellm lazy load should be < 5000ms, got {elapsed_ms:.2f}ms"


@pytest.mark.benchmark(group="lazy_loading")
def test_lazy_loading_patchright(benchmark):
    """Benchmark: patchright loads on first use"""

    def check_lazy_loading():
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import sys
from myrm_agent_harness.toolkits.browser import BrowserSession

# Should not load patchright
assert 'patchright' not in sys.modules, "patchright should not be loaded"
print("OK")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        if result.returncode != 0:
            raise AssertionError(f"Lazy loading check failed: {result.stderr}")
        return 0.0

    benchmark(check_lazy_loading)


@pytest.mark.benchmark(group="lazy_loading")
def test_lazy_loading_numpy(benchmark):
    """Benchmark: numpy loads on first use"""

    def check_lazy_loading():
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import sys
from myrm_agent_harness.toolkits.web_search import WebSearchTools

# Should not load numpy
assert 'numpy' not in sys.modules, "numpy should not be loaded"
print("OK")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        if result.returncode != 0:
            raise AssertionError(f"Lazy loading check failed: {result.stderr}")
        return 0.0

    benchmark(check_lazy_loading)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--benchmark-only"])
