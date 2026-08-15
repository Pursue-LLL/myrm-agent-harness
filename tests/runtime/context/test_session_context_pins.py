"""Tests for session_context_pins volume registry."""

from __future__ import annotations

import pytest

import myrm_agent_harness.runtime.context.session.session_context_pins as pins_module
from myrm_agent_harness.runtime.context.session.session_context_pins import (
    add_pinned_file,
    read_pinned_files,
    remove_pinned_file,
    write_pinned_files,
)


@pytest.fixture
def persistent_root(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> str:
    root = tmp_path / "persistent"
    root.mkdir()
    monkeypatch.setattr(pins_module, "PERSISTENT_ROOT", str(root))
    return str(root)


def test_read_pinned_files_empty_when_missing(persistent_root: str) -> None:
    assert read_pinned_files("session-1") == []


def test_write_and_read_roundtrip(persistent_root: str) -> None:
    record = write_pinned_files("session-1", ["src/a.py", "src/b.py"])
    assert list(record.files) == ["src/a.py", "src/b.py"]
    assert read_pinned_files("session-1") == ["src/a.py", "src/b.py"]


def test_add_pinned_file_dedupes_and_evicts(persistent_root: str) -> None:
    write_pinned_files("session-1", [f"src/{index}.py" for index in range(8)])
    record = add_pinned_file("session-1", "src/new.py")
    assert list(record.files)[-1] == "src/new.py"
    assert len(record.files) == 8
    assert "src/0.py" not in record.files


def test_remove_pinned_file(persistent_root: str) -> None:
    write_pinned_files("session-1", ["src/a.py", "src/b.py"])
    record = remove_pinned_file("session-1", "src/a.py")
    assert list(record.files) == ["src/b.py"]


def test_read_pinned_files_empty_session_id(persistent_root: str) -> None:
    assert read_pinned_files("") == []


def test_read_pinned_files_ignores_corrupt_payload(persistent_root: str) -> None:
    import json

    path = pins_module._pin_path("session-corrupt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{bad", encoding="utf-8")
    assert read_pinned_files("session-corrupt") == []

    path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    assert read_pinned_files("session-corrupt") == []

    path.write_text(json.dumps({"files": "bad"}), encoding="utf-8")
    assert read_pinned_files("session-corrupt") == []


def test_write_pinned_files_requires_session_id(persistent_root: str) -> None:
    with pytest.raises(ValueError, match="session_id"):
        write_pinned_files("", ["src/a.py"])


def test_add_pinned_file_skips_blank_path(persistent_root: str) -> None:
    write_pinned_files("session-1", ["src/a.py"])
    record = add_pinned_file("session-1", "   ")
    assert list(record.files) == ["src/a.py"]


def test_write_pinned_files_dedupes_and_caps(persistent_root: str) -> None:
    record = write_pinned_files(
        "session-1",
        [
            "src/a.py",
            " src/a.py ",
            "src/b.py",
            "",
            "src/c.py",
            "src/d.py",
            "src/e.py",
            "src/f.py",
            "src/g.py",
            "src/h.py",
        ],
    )
    assert list(record.files) == [
        "src/a.py",
        "src/b.py",
        "src/c.py",
        "src/d.py",
        "src/e.py",
        "src/f.py",
        "src/g.py",
        "src/h.py",
    ]
