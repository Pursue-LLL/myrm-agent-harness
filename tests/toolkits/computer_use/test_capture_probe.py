"""Tests for capture_probe.png_bytes_look_capturable."""

from __future__ import annotations

import builtins
import io

import pytest

from myrm_agent_harness.toolkits.computer_use.capture_probe import png_bytes_look_capturable


def _solid_png(color: tuple[int, int, int], size: tuple[int, int] = (64, 64)) -> bytes:
    from PIL import Image

    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _varied_png() -> bytes:
    from PIL import Image

    img = Image.new("RGB", (64, 64))
    for y in range(64):
        for x in range(64):
            img.putpixel((x, y), ((x * 3) % 256, (y * 5) % 256, 120))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_rejects_tiny_buffer() -> None:
    assert png_bytes_look_capturable(b"x" * 100) is False


def test_rejects_pure_black() -> None:
    assert png_bytes_look_capturable(_solid_png((0, 0, 0))) is False


def test_rejects_pure_white() -> None:
    assert png_bytes_look_capturable(_solid_png((255, 255, 255))) is False


def test_accepts_varied_frame() -> None:
    assert png_bytes_look_capturable(_varied_png()) is True


def test_rejects_when_pillow_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    data = _varied_png()
    for mod in [k for k in sys.modules if k == "PIL" or k.startswith("PIL.")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)

    real_import = builtins.__import__

    def _block_pil(name: str, *args: object, **kwargs: object) -> object:
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_pil)
    assert png_bytes_look_capturable(data) is False
