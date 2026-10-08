"""Unit tests for experience gene agent advice tool and MemoryManager mixin."""

from __future__ import annotations

import json

from myrm_agent_harness.toolkits.memory._manager.experience_evolution import (
    MemoryManagerExperienceEvolutionMixin,
)
from myrm_agent_harness.toolkits.memory.evolution.causal_extractor import (
    ExecutionStepSnapshot,
    MultiTurnTaskTrace,
)
from myrm_agent_harness.toolkits.memory.evolution.gene_ledger import (
    ExperienceGeneLedger,
)
from myrm_agent_harness.toolkits.memory.evolution.gene_models import (
    ExperienceGene,
    GenePolarity,
)
from myrm_agent_harness.toolkits.memory.evolution.tool import (
    create_experience_gene_advice_tool,
)


class DummyEvolutionMemoryManager(MemoryManagerExperienceEvolutionMixin):
    """Dummy MemoryManager subclass for testing experience evolution mixin."""

    def __init__(self) -> None:
        self.user_id = "test_user"


def _create_sample_ledger() -> ExperienceGeneLedger:
    ledger = ExperienceGeneLedger()
    gene1 = ExperienceGene(
        gene_id="gene-kernel-lock",
        trigger_signals=["kernel_panic", "driver_deadlock"],
        hypotheses_refuted=["reboot_machine", "disable_watchdog"],
        proven_resolution="Tune spinlock timeout in driver probe sequence",
        polarity=GenePolarity.POSITIVE,
        confidence_score=0.9,
        proof_count=3,
        tags=["kernel", "driver"],
    )
    gene2 = ExperienceGene(
        gene_id="gene-docker-perm",
        trigger_signals=["docker_permission_denied", "socket_error"],
        hypotheses_refuted=["chmod_777_root"],
        proven_resolution="Add daemon user to docker socket group and reload daemon",
        polarity=GenePolarity.POSITIVE,
        confidence_score=0.85,
        proof_count=2,
        tags=["docker", "sysadmin"],
    )
    ledger.register_or_reinforce(gene1)
    ledger.register_or_reinforce(gene2)
    return ledger


def test_experience_gene_tool_metadata() -> None:
    tool = create_experience_gene_advice_tool()
    assert tool.name == "inspect_experience_gene_advice"
    assert "experience" in tool.description.lower() or "gene" in tool.description.lower()


def test_experience_gene_tool_matches_active_signals() -> None:
    ledger = _create_sample_ledger()
    tool = create_experience_gene_advice_tool(ledger=ledger)

    raw_result = tool.invoke(
        {
            "active_signals": ["kernel_panic", "memory_leak"],
            "min_confidence": 0.5,
            "limit": 5,
        }
    )
    assert isinstance(raw_result, str)
    payload = json.loads(raw_result)

    assert payload["total_matches"] == 1
    advice = payload["advice"][0]
    assert advice["gene_id"] == "gene-kernel-lock"
    assert "kernel_panic" in advice["matched_signals"]
    assert "reboot_machine" in advice["refuted_paths"]
    assert "spinlock" in advice["recommended_resolution"].lower()
    assert advice["confidence"] >= 0.9


def test_experience_gene_tool_empty_match() -> None:
    ledger = _create_sample_ledger()
    tool = create_experience_gene_advice_tool(ledger=ledger)

    raw_result = tool.invoke(
        {
            "active_signals": ["unrelated_css_bug"],
            "min_confidence": 0.8,
            "limit": 5,
        }
    )
    payload = json.loads(raw_result)
    assert payload["total_matches"] == 0
    assert payload["advice"] == []


def test_memory_manager_mixin_query_advice() -> None:
    manager = DummyEvolutionMemoryManager()
    ledger = _create_sample_ledger()

    advices = manager.get_planning_gene_mutation_advice(
        active_signals=["docker_permission_denied"],
        min_confidence=0.7,
        ledger=ledger,
    )
    assert len(advices) == 1
    assert advices[0].gene_id == "gene-docker-perm"
    assert "chmod_777_root" in advices[0].refuted_paths


def test_memory_manager_mixin_extract_and_reinforce() -> None:
    manager = DummyEvolutionMemoryManager()
    ledger = ExperienceGeneLedger()

    trace = MultiTurnTaskTrace(
        session_id="session-trace-01",
        task_goal="clean cache files",
        steps=[
            ExecutionStepSnapshot(
                step_index=1,
                tool_name="bash",
                tool_input_summary="rm -rf cache",
                tool_output_snippet="permission denied",
                is_failure=True,
                error_signature="permission_denied",
            ),
            ExecutionStepSnapshot(
                step_index=2,
                tool_name="fs_chown",
                tool_input_summary="chown user:user cache",
                tool_output_snippet="success",
                is_failure=False,
            ),
        ],
        success_verified=True,
        final_solution_summary="Execute chown before directory operations",
    )


    genes = manager.extract_and_reinforce_causal_genes(trace, ledger=ledger)
    assert len(genes) >= 1
    assert any(g.polarity == GenePolarity.POSITIVE for g in genes)

    stats = manager.get_experience_gene_stats(ledger=ledger)
    assert stats["total_genes"] >= 1


def test_memory_manager_mixin_penalize_and_stats() -> None:
    manager = DummyEvolutionMemoryManager()
    ledger = _create_sample_ledger()

    penalized = manager.penalize_experience_gene("gene-kernel-lock", penalty=0.3, ledger=ledger)
    assert penalized is not None
    assert penalized.confidence_score <= 0.7

    genes = manager.list_experience_genes(ledger=ledger)
    assert len(genes) == 2

    stats = manager.get_experience_gene_stats(ledger=ledger)
    assert stats["total_genes"] == 2
