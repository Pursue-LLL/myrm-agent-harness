"""Unit tests for MAP-Elites Gene Bank Archive in Harness Evolution."""

from datetime import datetime

from myrm_agent_harness.agent.skills.evolution.core.gene_bank import GeneBankArchive
from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionLayer,
    FailurePathology,
    GeneCellKey,
    GeneEliteRecord,
    VerificationProof,
)


def test_gene_bank_archive_record_and_coverage():
    archive = GeneBankArchive(max_elites_per_cell=2)

    key_code_timeout = GeneCellKey(
        layer=EvolutionLayer.TOOL_CODE, pathology=FailurePathology.TIMEOUT_RETRY
    )
    rec1 = GeneEliteRecord(
        cell_key=key_code_timeout,
        skill_name="crawler-tool",
        patch_summary="Add retry backoff to crawler script",
        patch_content="def crawl(): retry_with_backoff()",
        fitness_score=0.85,
        verification_proof=VerificationProof(is_verified=True, success_streak=3),
    )

    admitted = archive.record_elite(rec1)
    assert admitted is True

    elites = archive.get_cell_elites(key_code_timeout)
    assert len(elites) == 1
    assert elites[0].skill_name == "crawler-tool"
    assert elites[0].fitness_score == 0.85

    # Add second elite with higher score
    rec2 = GeneEliteRecord(
        cell_key=key_code_timeout,
        skill_name="crawler-tool-v2",
        patch_summary="Add adaptive timeout header",
        patch_content="def crawl(): set_adaptive_timeout()",
        fitness_score=0.92,
        verification_proof=VerificationProof(is_verified=True, success_streak=4),
    )
    archive.record_elite(rec2)

    elites = archive.get_cell_elites(key_code_timeout)
    assert len(elites) == 2
    assert elites[0].fitness_score == 0.92  # Sorted desc

    # Add third elite with lower score than worst (0.80 < 0.85) -> should be rejected
    rec3 = GeneEliteRecord(
        cell_key=key_code_timeout,
        skill_name="crawler-tool-v3",
        patch_summary="Simple timeout 10",
        patch_content="def crawl(): timeout=10",
        fitness_score=0.80,
    )
    admitted_low = archive.record_elite(rec3)
    assert admitted_low is False
    assert len(archive.get_cell_elites(key_code_timeout)) == 2

    # Verify coverage matrix
    matrix = archive.get_coverage_matrix()
    assert matrix[EvolutionLayer.TOOL_CODE.value][FailurePathology.TIMEOUT_RETRY.value] == 2
    assert matrix[EvolutionLayer.PROMPT.value][FailurePathology.PARAM_ERROR.value] == 0


def test_gene_bank_archive_diversity_retrieval_and_serialization():
    archive = GeneBankArchive(max_elites_per_cell=2)

    key_prompt = GeneCellKey(layer=EvolutionLayer.PROMPT, pathology=FailurePathology.PARAM_ERROR)
    key_code = GeneCellKey(layer=EvolutionLayer.TOOL_CODE, pathology=FailurePathology.PARAM_ERROR)
    key_config = GeneCellKey(
        layer=EvolutionLayer.RUNTIME_CONFIG, pathology=FailurePathology.TIMEOUT_RETRY
    )

    archive.record_elite(
        GeneEliteRecord(
            cell_key=key_prompt,
            skill_name="sql-query",
            patch_summary="Clarify SQL schema prompt",
            patch_content="Guideline: specify schema explicitly",
            fitness_score=0.88,
        )
    )
    archive.record_elite(
        GeneEliteRecord(
            cell_key=key_code,
            skill_name="sql-query",
            patch_summary="Validate parameter dictionary types",
            patch_content="assert isinstance(params, dict)",
            fitness_score=0.82,
        )
    )
    archive.record_elite(
        GeneEliteRecord(
            cell_key=key_config,
            skill_name="db-connector",
            patch_summary="Set pool_timeout=30 in config",
            patch_content="pool_timeout: 30",
            fitness_score=0.90,
        )
    )

    diverse = archive.get_diverse_elites(target_pathology=FailurePathology.PARAM_ERROR)
    # Should contain prompt, tool_code and runtime_config (via fallback)
    assert len(diverse) == 3
    layers_found = {e.cell_key.layer for e in diverse}
    assert EvolutionLayer.PROMPT in layers_found
    assert EvolutionLayer.TOOL_CODE in layers_found
    assert EvolutionLayer.RUNTIME_CONFIG in layers_found

    # Test serialization & deserialization roundtrip
    serialized = archive.to_dict()
    assert "coverage" in serialized
    assert serialized["max_elites_per_cell"] == 2

    restored = GeneBankArchive.from_dict(serialized)
    restored_elites = restored.get_cell_elites(key_prompt)
    assert len(restored_elites) == 1
    assert restored_elites[0].patch_summary == "Clarify SQL schema prompt"


def test_variant_generator_prompt_integration_with_gene_bank_priors():
    """Verify VariantGenerator properly builds the gene bank prior section."""
    from myrm_agent_harness.agent.skills.evolution.core.types import SkillRecord
    from myrm_agent_harness.agent.skills.evolution.pipeline.variant_generator import VariantGenerator

    generator = VariantGenerator(llm=None)
    key_prompt = GeneCellKey(layer=EvolutionLayer.PROMPT, pathology=FailurePathology.PARAM_ERROR)
    priors = [
        GeneEliteRecord(
            cell_key=key_prompt,
            skill_name="test-skill",
            patch_summary="Add schema validation note to prompt",
            patch_content="...",
            fitness_score=0.9,
        )
    ]
    skill = SkillRecord(
        id="s1",
        name="test-skill",
        description="A test skill",
        content="Original content",
    )
    # Attach priors dynamically as attribute
    setattr(skill, "gene_bank_priors", priors)

    prompt = generator._build_variant_prompt(skill, "param error", "trace")
    assert "Diverse Multi-Layer Defensive Exemplars (MAP-Elites Prior)" in prompt
    assert "[PROMPT] Add schema validation note to prompt" in prompt

