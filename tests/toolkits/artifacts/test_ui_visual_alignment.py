from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.artifacts.ui_alignment import (
    UiDesignVisualAlignmentEngine,
    UiVariant,
    VisualAnnotation,
)


def test_register_and_retrieve_variants() -> None:
    engine = UiDesignVisualAlignmentEngine()
    session_id = "test-session-001"

    variant_1 = UiVariant(
        variant_id="var_bento_01",
        title="Modern Bento Grid",
        style_theme="modern_bento",
        html_content="<div class='bento-grid'><card>Metric A</card></div>",
        css_tokens={"--bg-card": "#18181b", "--border": "#27272a"},
        description="High density modern card dashboard",
    )
    engine.register_variant(session_id, variant_1)

    variants = engine.get_variants(session_id)
    assert len(variants) == 1
    assert variants[0].variant_id == "var_bento_01"
    assert variants[0].title == "Modern Bento Grid"

    # Test update existing variant
    variant_updated = UiVariant(
        variant_id="var_bento_01",
        title="Updated Bento Grid",
        style_theme="modern_bento",
        html_content="<div class='bento-grid-v2'><card>Metric B</card></div>",
    )
    engine.register_variant(session_id, variant_updated)
    updated_variants = engine.get_variants(session_id)
    assert len(updated_variants) == 1
    assert updated_variants[0].title == "Updated Bento Grid"


def test_canvas_visual_annotations() -> None:
    engine = UiDesignVisualAlignmentEngine()
    variant_id = "var_bento_01"

    note_1 = VisualAnnotation(
        annotation_id="anno_01",
        variant_id=variant_id,
        x=15.0,
        y=20.0,
        width=30.0,
        height=15.0,
        comment="Increase metric font size and emphasize contrast",
        label="typography_contrast",
    )
    engine.add_annotation(variant_id, note_1)

    notes = engine.get_annotations(variant_id)
    assert len(notes) == 1
    assert notes[0].annotation_id == "anno_01"
    assert notes[0].x == 15.0
    assert "contrast" in notes[0].comment


def test_compile_visual_contract_success() -> None:
    engine = UiDesignVisualAlignmentEngine()
    session_id = "test-session-compile"
    variant_id = "var_minimal_01"

    variant = UiVariant(
        variant_id=variant_id,
        title="Minimal Dark Theme",
        style_theme="minimal_dark",
        html_content="<main class='dark-container'><header>Title</header></main>",
        css_tokens={"--primary": "#6366f1", "--bg": "#09090b"},
        description="Clean aesthetic with neon accents",
    )
    engine.register_variant(session_id, variant)

    note = VisualAnnotation(
        annotation_id="anno_header",
        variant_id=variant_id,
        x=5.0,
        y=5.0,
        width=90.0,
        height=10.0,
        comment="Make header sticky with backdrop-blur",
        label="layout_interaction",
    )
    engine.add_annotation(variant_id, note)

    contract = engine.compile_visual_contract(session_id, variant_id)
    assert contract.session_id == session_id
    assert contract.approved_variant_id == variant_id
    assert contract.style_theme == "minimal_dark"
    assert len(contract.annotations) == 1
    assert "VISUAL DESIGN CONTRACT ENFORCEMENT" in contract.enforcement_prompt
    assert "--primary: #6366f1" in contract.enforcement_prompt
    assert "backdrop-blur" in contract.enforcement_prompt

    latest = engine.get_latest_contract(session_id)
    assert latest is not None
    assert latest.contract_id == contract.contract_id


def test_compile_visual_contract_not_found() -> None:
    engine = UiDesignVisualAlignmentEngine()
    session_id = "test-session-error"

    with pytest.raises(ValueError, match="Variant 'non_existent' not found"):
        engine.compile_visual_contract(session_id, "non_existent")
