"""Architecture tests for skill semantic modifiers parser and audience adapter."""

from __future__ import annotations

import pytest

from myrm_agent_harness.backends.skills.runtime_modifiers import (
    AudienceDepth,
    parse_skill_modifiers,
)


def test_parse_eli5_modifier() -> None:
    res = parse_skill_modifiers("/explain ELI5 quantum computing")
    assert res.audience_depth == AudienceDepth.ELI5
    assert res.clean_command == "/explain quantum computing"
    assert "ELI5" in res.modifiers

    patched = res.apply_to_prompt("Explain the topic.")
    assert "[AUDIENCE COGNITIVE PATCH: ELI5 MODE]" in patched
    assert "Target Audience: Complete beginner" in patched


def test_parse_chinese_executive_modifier() -> None:
    res = parse_skill_modifiers("/summary 高管 Q3 营收数据")
    assert res.audience_depth == AudienceDepth.EXECUTIVE
    assert res.clean_command == "/summary Q3 营收数据"
    assert "高管" in res.modifiers

    patched = res.apply_to_prompt("请做总结")
    assert "[AUDIENCE COGNITIVE PATCH: EXECUTIVE BRIEFING]" in patched
    assert "Bottom-Line-Up-Front" in res.profile.tone_directives[0]


def test_parse_senior_modifier() -> None:
    res = parse_skill_modifiers("/review --senior 分布式一致性协议实现")
    assert res.audience_depth == AudienceDepth.SENIOR
    assert res.clean_command == "/review 分布式一致性协议实现"

    patched = res.apply_to_prompt("代码审查要求")
    assert "[AUDIENCE COGNITIVE PATCH: SENIOR SPECIALIST]" in patched


def test_standard_fallback_without_modifiers() -> None:
    res = parse_skill_modifiers("帮我写一个 Python 脚本")
    assert res.audience_depth == AudienceDepth.STANDARD
    assert res.clean_command == "帮我写一个 Python 脚本"
    assert not res.modifiers

    base = "Original prompt text."
    assert res.apply_to_prompt(base) == base
