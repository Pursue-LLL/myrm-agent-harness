"""Atomic text writes for OKF cognitive map artifacts.

[INPUT]
- pathlib::Path (POS: filesystem path operations)

[OUTPUT]
- atomic_write_text: atomic write helper via temporary file replace

[POS]
OKF 认知地图底层原子写入工具函数。
"""

from __future__ import annotations

from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)
