"""Unit tests for persona semantic conflict probe and mutual exclusion resolver."""

from __future__ import annotations

from myrm_agent_harness.runtime.context.persona_conflict_resolver import (
    PersonaMutualExclusionResolver,
    PersonaSemanticConflictProbe,
    PolarityPatternRegistry,
)
from myrm_agent_harness.runtime.context.persona_conflict_resolver_types import (
    PersonaSourceTier,
    PolarityDimension,
)


def test_polarity_pattern_matching() -> None:
    """Verifies recognition of opposing sides across semantic polarity dimensions."""
    gentle_text = "请保持温柔可爱的语气，做贴心顺从的萌系小助手。"
    matched_gentle = PolarityPatternRegistry.match_polarities(gentle_text)
    assert PolarityDimension.GENTLE_VS_BLUNT in matched_gentle
    side, hits = matched_gentle[PolarityDimension.GENTLE_VS_BLUNT]
    assert side == "A"
    assert "温柔" in hits or "可爱" in hits

    blunt_text = "说话要暴躁毒舌硬核，直言不讳指出缺陷。"
    matched_blunt = PolarityPatternRegistry.match_polarities(blunt_text)
    assert PolarityDimension.GENTLE_VS_BLUNT in matched_blunt
    side_b, hits_b = matched_blunt[PolarityDimension.GENTLE_VS_BLUNT]
    assert side_b == "B"
    assert "暴躁" in hits_b or "毒舌" in hits_b

    terse_text = "回答必须极简，绝不多说一句废话，采用 caveman ultra-compact 模式。"
    matched_terse = PolarityPatternRegistry.match_polarities(terse_text)
    assert PolarityDimension.VERBOSITY_VS_TERSE in matched_terse
    assert matched_terse[PolarityDimension.VERBOSITY_VS_TERSE][0] == "B"


def test_semantic_conflict_probe_detection() -> None:
    """Verifies that antagonistic persona directives between system and user are detected."""
    snip_sys = PersonaMutualExclusionResolver.create_snippet(
        snippet_id="sys_cute",
        content="你是一个温柔可爱、说话萌萌哒的贴心助手。",
        tier=PersonaSourceTier.SYSTEM_DEFAULT,
    )
    snip_user = PersonaMutualExclusionResolver.create_snippet(
        snippet_id="user_rough",
        content="你是一个硬核暴躁的大老粗工程师，说话直言不讳冷酷毒舌。",
        tier=PersonaSourceTier.USER_CUSTOM,
    )

    conflicts = PersonaSemanticConflictProbe.scan_conflicts([snip_sys, snip_user])
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.dimension == PolarityDimension.GENTLE_VS_BLUNT
    assert c.dominant_snippet.snippet_id == "user_rough"
    assert c.subordinate_snippet.snippet_id == "sys_cute"
    assert "sys_cute" in c.explanation
    assert len(c.conflicting_keywords_dominant) > 0
    assert len(c.conflicting_keywords_subordinate) > 0


def test_mutual_exclusion_resolution_and_clean_synthesis() -> None:
    """Verifies that conflict resolver drops subordinated snippets and synthesizes unified persona."""
    resolver = PersonaMutualExclusionResolver()

    snip_sys = PersonaMutualExclusionResolver.create_snippet(
        snippet_id="sys_default",
        content="保持萌萌哒温柔可爱的甜美语气。",
        tier=PersonaSourceTier.SYSTEM_DEFAULT,
    )
    snip_user = PersonaMutualExclusionResolver.create_snippet(
        snippet_id="user_custom",
        content="硬核暴躁大老粗风格，只关注技术本质，拒绝虚假礼貌。",
        tier=PersonaSourceTier.USER_CUSTOM,
    )
    snip_neutral = PersonaMutualExclusionResolver.create_snippet(
        snippet_id="neutral_tech",
        content="遵循 Python PEP8 规范并提供具体的类型注解。",
        tier=PersonaSourceTier.WORKSPACE_RULE,
    )

    result = resolver.resolve_conflicts([snip_sys, snip_user, snip_neutral])
    assert result.is_conflict_free is False
    assert len(result.conflicts_detected) == 1

    # Invariant: sys_default must be dropped, user_custom and neutral_tech retained
    dropped_ids = [s.snippet_id for s in result.dropped_conflicting_snippets]
    retained_ids = [s.snippet_id for s in result.retained_snippets]
    assert dropped_ids == ["sys_default"]
    assert "user_custom" in retained_ids
    assert "neutral_tech" in retained_ids

    # Unified prompt check
    assert "硬核暴躁大老粗" in result.resolved_persona_text
    assert "PEP8" in result.resolved_persona_text
    assert "萌萌哒" not in result.resolved_persona_text


def test_multi_dimension_cascading_conflicts() -> None:
    """Verifies simultaneous arbitration across multiple polarity dimensions."""
    resolver = PersonaMutualExclusionResolver()

    snippets = [
        PersonaMutualExclusionResolver.create_snippet(
            "s1", "说话萌萌哒温柔贴心，并且回答时详细展开逐步细致论述。", PersonaSourceTier.SYSTEM_DEFAULT
        ),
        PersonaMutualExclusionResolver.create_snippet(
            "s2", "硬核暴躁大老粗，且回答必须极简无废话一句话回答。", PersonaSourceTier.USER_CUSTOM
        ),
    ]

    result = resolver.resolve_conflicts(snippets)
    assert len(result.conflicts_detected) == 2
    dimensions = {c.dimension for c in result.conflicts_detected}
    assert PolarityDimension.GENTLE_VS_BLUNT in dimensions
    assert PolarityDimension.VERBOSITY_VS_TERSE in dimensions
    assert len(result.dropped_conflicting_snippets) == 1
    assert result.dropped_conflicting_snippets[0].snippet_id == "s1"
    assert result.retained_snippets[0].snippet_id == "s2"


def test_conflict_free_snippets_pass_through() -> None:
    """Verifies that non-clashing, harmonious persona directives pass through cleanly."""
    resolver = PersonaMutualExclusionResolver()

    snippets = [
        PersonaMutualExclusionResolver.create_snippet(
            "s1", "遵循架构设计原则，坚持原则有主见敢于质疑。", PersonaSourceTier.SYSTEM_DEFAULT
        ),
        PersonaMutualExclusionResolver.create_snippet(
            "s2", "采用正式学术书面语，说话庄重严谨。", PersonaSourceTier.USER_CUSTOM
        ),
    ]

    result = resolver.resolve_conflicts(snippets)
    assert result.is_conflict_free is True
    assert len(result.conflicts_detected) == 0
    assert len(result.dropped_conflicting_snippets) == 0
    assert len(result.retained_snippets) == 2
    assert "敢于质疑" in result.resolved_persona_text
    assert "正式学术" in result.resolved_persona_text
