"""Universal thin prompt generator for adaptive agent harnesses.

Constructs minimal, high-signal system prompt skeletons tailored to model
capability tiers and operational discipline modes (Pure, Lean, Audit),
eliminating CoT phase interference and preserving user persona fidelity.
"""

from __future__ import annotations

import math

from .universal_thin_harness_types import (
    ModelCapabilityTier,
    OperatingDisciplineMode,
    ThinPromptContract,
)


class UniversalThinPromptGenerator:
    """Generates ultra-thin system prompts adapting to model tiers and operational modes."""

    def __init__(self, chars_per_token_ratio: float = 3.8) -> None:
        self._chars_per_token_ratio = chars_per_token_ratio

    def estimate_tokens(self, text: str) -> int:
        """Estimates token count deterministically based on character count."""
        if not text.strip():
            return 0
        return max(1, math.ceil(len(text) / self._chars_per_token_ratio))

    def build_contract(
        self,
        mode: OperatingDisciplineMode,
        capability_tier: ModelCapabilityTier,
        custom_persona: str = "",
    ) -> ThinPromptContract:
        """Constructs a tailored ThinPromptContract based on mode and capability tier."""
        persona = custom_persona.strip()

        if mode == OperatingDisciplineMode.PURE:
            core = self._build_pure_skeleton(capability_tier)
            native_cot = True
        elif mode == OperatingDisciplineMode.LEAN:
            core = self._build_lean_skeleton(capability_tier)
            native_cot = capability_tier == ModelCapabilityTier.FRONTIER
        else:  # AUDIT
            core = self._build_audit_skeleton(capability_tier)
            native_cot = False

        overhead_tokens = self.estimate_tokens(core)

        return ThinPromptContract(
            mode=mode,
            capability_tier=capability_tier,
            system_prompt_core=core,
            custom_persona_prompt=persona,
            estimated_overhead_tokens=overhead_tokens,
            is_native_cot_passthrough=native_cot,
            metadata={
                "core_char_len": str(len(core)),
                "has_custom_persona": str(bool(persona)),
            },
        )

    def assemble_system_message(
        self,
        contract: ThinPromptContract,
    ) -> str:
        """Assembles the final system prompt ensuring persona primacy in Pure mode."""
        if contract.mode == OperatingDisciplineMode.PURE:
            # In Pure mode, custom persona takes priority, followed by minimal core
            if contract.custom_persona_prompt:
                return f"{contract.custom_persona_prompt}\n\n[Baseline Discipline]\n{contract.system_prompt_core}"
            return contract.system_prompt_core

        # In Lean and Audit modes, foundational security/audit rules frame the persona
        if contract.custom_persona_prompt:
            return f"{contract.system_prompt_core}\n\n[Custom Role & Persona]\n{contract.custom_persona_prompt}"
        return contract.system_prompt_core

    def _build_pure_skeleton(self, tier: ModelCapabilityTier) -> str:
        """Ultra-thin skeleton (<200 tokens) relying on native model post-training."""
        if tier == ModelCapabilityTier.FRONTIER:
            return (
                "You are an autonomous AI companion. Execute tasks directly and concisely. "
                "Use tools when external state or facts are required. Avoid unnecessary meta-commentary, "
                "redundant planning chatter, and synthetic reasoning demonstrations."
            )
        if tier == ModelCapabilityTier.STANDARD:
            return (
                "You are a helpful AI assistant. Answer accurately and directly. "
                "Invoke tools when factual inspection or file changes are required. "
                "Provide clean results without repeating obvious constraints."
            )
        # LEGACY
        return (
            "You are an AI assistant. Follow user instructions step-by-step. "
            "Inspect files before modifying them, and explain actions clearly."
        )

    def _build_lean_skeleton(self, tier: ModelCapabilityTier) -> str:
        """Pragmatic engineering skeleton (~300-450 tokens) with minimal sufficient checks."""
        base = (
            "You are an expert engineering agent. Follow the principle of minimum sufficient operations:\n"
            "1. Inspect target files or environments before applying modifications.\n"
            "2. Execute changes cleanly without unnecessary intermediate exploratory probes.\n"
            "3. Verify outcomes with targeted unit tests or status checks.\n"
            "4. Report concise summaries of what changed and verified evidence."
        )
        if tier == ModelCapabilityTier.FRONTIER:
            return f"{base}\nTrust native reasoning capabilities; avoid verbose mechanical chain-of-thought."
        return f"{base}\nState key assumptions before executing multi-file mutations."

    def _build_audit_skeleton(self, tier: ModelCapabilityTier) -> str:
        """Strict governance skeleton for security-sensitive, financial, and compliant domains."""
        return (
            "You are an audited governance agent operating under strict compliance policy:\n"
            "1. Zero-trust verification: every modification must provide verifiable before-and-after evidence.\n"
            "2. Invariant preservation: never bypass security perimeters, RBAC policies, or secret masks.\n"
            "3. Explicit justification: record reasons for every external tool call and state change.\n"
            "4. Fail-closed: halt execution immediately upon encountering policy violations or ambiguous authorization."
        )
