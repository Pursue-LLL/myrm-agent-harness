"""Shared fixtures for the LLM core tests."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.utils import model_utils


@pytest.fixture(autouse=True)
def _unmapped_output_ceilings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every model to "ceiling unknown" so budget expectations never depend on LiteLLM's price table.

    The table differs between LiteLLM's remote and bundled copies, so a real-model assertion on
    a raised ``max_tokens`` would flip with the network. Tests of the clamp itself override this
    with an explicit ceiling.
    """
    monkeypatch.setattr(model_utils, "get_model_output_ceiling", lambda _model: None)
