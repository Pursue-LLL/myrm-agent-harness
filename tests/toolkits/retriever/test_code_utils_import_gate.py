"""Import-gate tests for optional [retrieval] extra in code_utils."""

from __future__ import annotations

import builtins
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.retriever.splitter import code_utils


def test_get_langchain_splitters_raises_retrieval_install_hint() -> None:
    real_import = builtins.__import__

    def _import(name: str, *args: object, **kwargs: object) -> object:
        if name == "langchain_text_splitters" or name.startswith("langchain_text_splitters."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_import):
        with pytest.raises(ImportError, match="langchain-text-splitters is required"):
            code_utils._get_langchain_splitters()
