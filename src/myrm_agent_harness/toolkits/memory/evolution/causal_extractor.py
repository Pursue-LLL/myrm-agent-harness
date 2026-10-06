# [POS] toolkits/memory/evolution/causal_extractor.py
# [INPUT] gene_models.ExperienceGene, gene_models.GenePolarity
# [OUTPUT] CausalGeneExtractor

"""Causal Experience Gene Extractor for multi-turn execution trajectories."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field

from .gene_models import ExperienceGene, GenePolarity


@dataclass(frozen=True)
class ExecutionStepSnapshot:
    """Snapshot of a single execution step within a multi-turn task."""

    step_index: int
    tool_name: str
    tool_input_summary: str
    tool_output_snippet: str
    is_failure: bool
    error_signature: str = ""


@dataclass(frozen=True)
class MultiTurnTaskTrace:
    """Multi-turn execution trace of a trial-error-resolution task session."""

    session_id: str
    task_goal: str
    steps: list[ExecutionStepSnapshot] = field(default_factory=list)
    success_verified: bool = False
    final_solution_summary: str = ""


class CausalGeneExtractor:
    """Extracts causal experience genes from multi-turn trial-error-success trajectories."""

    @classmethod
    def extract_gene(
        cls,
        trace: MultiTurnTaskTrace,
        domain_tag: str = "debugging",
    ) -> ExperienceGene | None:
        """Extract a structured ExperienceGene from the given multi-turn task trace."""
        if not trace.steps or not trace.success_verified:
            return None

        # 1. Identify failure turns and dead-end hypotheses
        failed_steps = [s for s in trace.steps if s.is_failure]
        if not failed_steps:
            # If no failures occurred, it's a routine execution without counterfactual divergence
            return None

        trigger_signals: set[str] = set()
        refuted_hypotheses: list[str] = []

        for step in failed_steps:
            # Extract trigger signals
            if step.tool_name:
                trigger_signals.add(f"tool:{step.tool_name.lower()}")
            if step.error_signature:
                cleaned_err = cls._sanitize_error_signal(step.error_signature)
                if cleaned_err:
                    trigger_signals.add(cleaned_err)

            # Summarize the refuted action hypothesis
            hypo_text = f"Attempted [{step.tool_name}] with {step.tool_input_summary}"
            if step.error_signature:
                hypo_text += f" -> Failed: {step.error_signature[:60]}"
            refuted_hypotheses.append(hypo_text)

        # 2. Extract proven resolution
        resolution = trace.final_solution_summary.strip()
        if not resolution:
            # Fallback to the last successful step
            success_steps = [s for s in trace.steps if not s.is_failure]
            if success_steps:
                last_s = success_steps[-1]
                resolution = f"Execute [{last_s.tool_name}] with {last_s.tool_input_summary}"
            else:
                resolution = "Verified resolution recorded from task completion"

        # 3. Formulate gene ID
        signal_fingerprint = hashlib.sha256(
            "::".join(sorted(trigger_signals)).encode()
        ).hexdigest()[:10]
        gene_id = f"gene_{domain_tag}_{signal_fingerprint}"

        tags = [domain_tag]
        if any("bash" in sig for sig in trigger_signals):
            tags.append("system")
        if any("permission" in sig.lower() for sig in trigger_signals):
            tags.append("security")
        if any("network" in sig.lower() or "connection" in sig.lower() for sig in trigger_signals):
            tags.append("network")

        return ExperienceGene(
            gene_id=gene_id,
            trigger_signals=sorted(trigger_signals),
            hypotheses_refuted=refuted_hypotheses[:8],
            proven_resolution=resolution,
            polarity=GenePolarity.POSITIVE,
            confidence_score=0.8,
            proof_count=1,
            provenance_session_id=trace.session_id,
            tags=sorted(tags),
            created_at=time.time(),
            updated_at=time.time(),
        )

    @staticmethod
    def _sanitize_error_signal(error_text: str) -> str:
        """Strip dynamic parameters (pids, timestamps, memory addresses) to produce stable signal."""
        text = error_text.strip()
        # Remove timestamps
        text = re.sub(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?\b", "", text)
        # Remove memory addresses (0x...)
        text = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", text)
        # Remove process IDs (pid 12345)
        text = re.sub(r"\bpid\s+\d+\b", "pid PID", text, flags=re.IGNORECASE)
        # Remove port numbers
        text = re.sub(r":\d{4,5}\b", ":PORT", text)
        # Truncate and clean whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text[:80]
