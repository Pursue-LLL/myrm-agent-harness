"""Architecture tests for compiled-core release metadata injection."""

from __future__ import annotations

from harness_packaging.compiled_core_extra import inject_compiled_core_extra


def test_inject_compiled_core_extra_adds_six_platform_deps() -> None:
    sample = "[project]\nname = \"x\"\n\n[tool.uv]\n"
    out = inject_compiled_core_extra(sample, "0.1.0rc1")
    assert "compiled-core = [" in out
    assert out.count("myrm-agent-harness-core-") == 6
    assert "==0.1.0rc1" in out


def test_inject_compiled_core_extra_is_idempotent() -> None:
    sample = "[project]\ncompiled-core = []\n\n[tool.uv]\n"
    assert inject_compiled_core_extra(sample, "0.1.0rc1") == sample
