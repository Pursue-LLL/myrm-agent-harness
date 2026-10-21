"""Importing the web search toolkit must not load litellm.

[INPUT]
- myrm_agent_harness.toolkits.web_search: public toolkit facade
- myrm_agent_harness.toolkits.web_search.providers: provider package with lazy ``LiteLLMSearch``

[OUTPUT]
- Regression guard for the startup contract that litellm loads on first search, not on import.

[POS]
Unit tests mirroring src/myrm_agent_harness/toolkits/web_search/providers/__init__.py.
"""

from __future__ import annotations

import subprocess
import sys


def _run(probe: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=False)


def test_importing_the_toolkit_does_not_load_litellm() -> None:
    result = _run(
        "import sys; "
        "from myrm_agent_harness.toolkits.web_search import WebSearchTools; "
        "assert 'litellm' not in sys.modules"
    )
    assert result.returncode == 0, result.stderr


def test_litellm_search_loads_on_first_access() -> None:
    result = _run(
        "import sys; "
        "from myrm_agent_harness.toolkits.web_search.providers import LiteLLMSearch; "
        "assert LiteLLMSearch.__name__ == 'LiteLLMSearch'; "
        "assert 'litellm' in sys.modules"
    )
    assert result.returncode == 0, result.stderr
