"""Architecture test: harness _ARCH.md must not use lazy placeholder phrases."""

from __future__ import annotations

from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).resolve().parent.parent.parent / "src"
_BANNED = (
    "见源码",
    "retrievalhandlestool",
    "documentpre-handlesmodule",
    "textsplittoolmodule",
)


def _arch_files() -> list[Path]:
    files: list[Path] = []
    for path in _SRC_ROOT.rglob("_ARCH.md"):
        if "__pycache__" in path.parts:
            continue
        files.append(path)
    return sorted(files)


@pytest.mark.architecture
@pytest.mark.parametrize("arch_path", _arch_files(), ids=lambda p: p.parent.name)
def test_harness_arch_no_lazy_placeholders(arch_path: Path) -> None:
    text = arch_path.read_text(encoding="utf-8")
    for phrase in _BANNED:
        assert phrase not in text, f"{arch_path}: contains banned placeholder {phrase!r}"
