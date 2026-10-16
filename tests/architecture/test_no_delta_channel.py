"""Architecture guard: no graph may use ``DeltaChannel`` while checkpoint history is pruned.

A ``DeltaChannel`` stores only a sentinel in most checkpoints and rebuilds its value by walking older checkpoints and
their writes. ``runtime/checkpointing/pruning.py`` deletes exactly those, so a graph using the channel would silently
resume with an empty value. Pruning is safe only for as long as this test passes; making the pruner delta-aware is the
precondition for adding the first ``DeltaChannel``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_HARNESS_SRC = _REPO_ROOT / "src" / "myrm_agent_harness"
_CHANNEL_NAME = "DeltaChannel"


def _uses_delta_channel(source: str) -> bool:
    """Whether the code imports or references the channel type; docstrings and comments do not count."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id == _CHANNEL_NAME:
            return True
        if isinstance(node, ast.Attribute) and node.attr == _CHANNEL_NAME:
            return True
        if isinstance(node, ast.alias) and node.name.split(".")[-1] == _CHANNEL_NAME:
            return True
    return False


@pytest.mark.architecture
def test_harness_source_uses_no_delta_channel() -> None:
    offenders = [
        py_file.relative_to(_HARNESS_SRC).as_posix()
        for py_file in sorted(_HARNESS_SRC.rglob("*.py"))
        if _CHANNEL_NAME in (text := py_file.read_text(encoding="utf-8")) and _uses_delta_channel(text)
    ]

    assert not offenders, (
        "DeltaChannel makes keep-latest checkpoint pruning lose state; make "
        f"PruningAsyncSqliteSaver delta-aware before using it: {offenders}"
    )


@pytest.mark.parametrize(
    "source",
    [
        "from langgraph.channels import DeltaChannel\n",
        "from langgraph.channels.delta import DeltaChannel as Delta\n",
        "import langgraph.channels\nchannel = langgraph.channels.DeltaChannel(int)\n",
        "channel = DeltaChannel(int)\n",
    ],
)
def test_detector_flags_every_way_of_using_the_channel(source: str) -> None:
    assert _uses_delta_channel(source)


def test_detector_ignores_prose_that_merely_names_the_channel() -> None:
    assert not _uses_delta_channel('"""Mentions DeltaChannel in prose."""\n# DeltaChannel in a comment\nvalue = 1\n')
