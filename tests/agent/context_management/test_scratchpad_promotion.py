"""Unit tests for ScratchpadPromotionEngine in context management."""


from myrm_agent_harness.agent.context_management.scratchpad_promotion import (
    ProjectSeed,
    PromotionConfig,
    ScratchpadDraft,
    ScratchpadPromotionEngine,
)


def test_compile_seed_default_config() -> None:
    draft = ScratchpadDraft(
        title="AI Code Review Assistant",
        content="An automated assistant that reads git diffs and reports actionable feedback.\nSupports python and typescript.",
        temporary_tags=["ai", "productivity"],
    )

    seed = ScratchpadPromotionEngine.compile_seed(draft)

    assert isinstance(seed, ProjectSeed)
    assert seed.project_name == "ai-code-review-assistant"
    assert seed.description == "An automated assistant that reads git diffs and reports actionable feedback."
    assert len(seed.seeded_documents) == 2

    # Check origin document
    origin_doc = next(d for d in seed.seeded_documents if d.relative_path == "docs/scratchpad_origin.md")
    assert "# Original Scratchpad: AI Code Review Assistant" in origin_doc.content
    assert "ai, productivity" in origin_doc.content
    assert "Supports python and typescript" in origin_doc.content

    # Check README
    readme_doc = next(d for d in seed.seeded_documents if d.relative_path == "README.md")
    assert "# ai-code-review-assistant" in readme_doc.content
    assert "Overview" in readme_doc.content

    # Check initial context prompt
    assert "<!-- PROJECT_PROMOTED_FROM_SCRATCHPAD -->" in seed.initial_context_prompt
    assert 'name="ai-code-review-assistant"' in seed.initial_context_prompt

    # Check provenance
    assert seed.provenance_metadata["source"] == "scratchpad"
    assert seed.provenance_metadata["original_title"] == "AI Code Review Assistant"


def test_compile_seed_custom_config() -> None:
    draft = ScratchpadDraft(
        title="Transient Ideas",
        content="Quick scratchpad notes about distributed consensus.",
    )
    config = PromotionConfig(
        target_project_name="raft-engine-core",
        init_readme=False,
    )

    seed = ScratchpadPromotionEngine.compile_seed(draft, config)

    assert seed.project_name == "raft-engine-core"
    assert len(seed.seeded_documents) == 1
    assert seed.seeded_documents[0].relative_path == "docs/scratchpad_origin.md"


def test_compile_seed_fallback_name_and_truncated_summary() -> None:
    long_first_line = "A" * 150
    draft = ScratchpadDraft(
        title="   !!!   ",  # Special characters only -> fallback to content
        content=f"{long_first_line}\nSecond line of description.",
    )

    seed = ScratchpadPromotionEngine.compile_seed(draft)

    assert seed.project_name != ""
    assert len(seed.description) <= 120
    assert seed.description.endswith("...")


def test_compile_seed_empty_content() -> None:
    draft = ScratchpadDraft(
        title="",
        content="",
    )

    seed = ScratchpadPromotionEngine.compile_seed(draft)

    assert seed.project_name == "scratchpad-project"
    assert seed.description == "Promoted project from scratchpad."
    assert len(seed.seeded_documents) == 2
