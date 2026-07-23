"""Tests for OperationContext STR_REPLACE edits validation."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.core.operation_context import (
    OperationContext,
    OperationType,
    StrReplaceEdit,
    ViewRange,
)


def test_view_range_to_slice() -> None:
    start, end = ViewRange(start=2, end=4).to_slice(10)
    assert start == 1
    assert end == 4

    start2, end2 = ViewRange(start=1, end=-1).to_slice(5)
    assert start2 == 0
    assert end2 == 5


def test_view_validate_requires_paths() -> None:
    ctx = OperationContext(operation=OperationType.VIEW, executor=None, paths=[])
    with pytest.raises(ValueError, match="requires 'paths'"):
        ctx.validate()


def test_create_validate_requires_fields() -> None:
    ctx = OperationContext(
        operation=OperationType.CREATE, executor=None, path=None, file_text="x"
    )
    with pytest.raises(ValueError, match="requires 'path'"):
        ctx.validate()

    ctx2 = OperationContext(
        operation=OperationType.CREATE, executor=None, path="f.py", file_text=None
    )
    with pytest.raises(ValueError, match="requires 'file_text'"):
        ctx2.validate()


def test_str_replace_validate_requires_path() -> None:
    ctx = OperationContext(
        operation=OperationType.STR_REPLACE,
        executor=None,
        path=None,
        edits=(StrReplaceEdit(old_str="a", new_str="b"),),
    )
    with pytest.raises(ValueError, match="requires 'path'"):
        ctx.validate()


def test_str_replace_validate_requires_edits() -> None:
    ctx = OperationContext(
        operation=OperationType.STR_REPLACE,
        executor=None,
        path="f.py",
        edits=(),
    )
    with pytest.raises(ValueError, match="non-empty 'edits'"):
        ctx.validate()


def test_str_replace_validate_requires_non_empty_old_str() -> None:
    ctx = OperationContext(
        operation=OperationType.STR_REPLACE,
        executor=None,
        path="f.py",
        edits=(StrReplaceEdit(old_str="", new_str="b"),),
    )
    with pytest.raises(ValueError, match="requires non-empty old_str"):
        ctx.validate()


def test_str_replace_validate_ok() -> None:
    ctx = OperationContext(
        operation=OperationType.STR_REPLACE,
        executor=None,
        path="f.py",
        edits=(StrReplaceEdit(old_str="a", new_str="b"),),
    )
    ctx.validate()
