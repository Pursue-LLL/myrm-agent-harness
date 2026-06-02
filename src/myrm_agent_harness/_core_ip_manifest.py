"""Core IP module import paths (sync with harness_packaging/core_manifest.yaml)."""

from __future__ import annotations

CORE_IP_IMPORTS: tuple[str, ...] = (
    "myrm_agent_harness.agent.skills.evolution.core.engine",
    "myrm_agent_harness.agent.skills.evolution.pipeline.trace_analyzer",
    "myrm_agent_harness.agent.skills.evolution.core.proposal_builder",
    "myrm_agent_harness.agent.context_management.pipeline.engine",
    "myrm_agent_harness.toolkits.memory.strategies.extractor",
    "myrm_agent_harness.toolkits.memory.cognitive.deriver",
)
