"""Cognitive Deriver (Async Dialectic Reasoning Engine).

Extracts implicit user preferences, communication styles, and decision logic from
recent conversation exchanges, storing them as Claim Nodes in the Memory Graph with
conflict resolution.

[POS]
Cognitive derivation module for implicit preference extraction using LLM and Claim Graph.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.types import ClaimConflictState

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

_DERIVER_PROMPT = """You are an advanced Cognitive Deriver analyzing a conversation.
Your goal is to extract deep, implicit user preferences, communication styles, and constraints from the interaction.
Look closely for friction, corrections, and explicit directives.

## Rules
1. Focus on HOW the user wants the AI to act, not the specific coding facts.
   You must pay special attention to these 3 core dimensions if they appear:
   - "reply_style": Formal/casual, concise/detailed, code-only/explained.
   - "cognitive_depth": Beginner/expert, needs underlying principles or just solutions.
   - "proactivity": Proactive warnings/passive execution.
2. Output ONLY a valid JSON array of objects.
3. Each object MUST have:
   - "preference_key": A short, slug-like identifier (e.g., "reply_style", "cognitive_depth", "proactivity", "coding_paradigm").
   - "preference_claim": A concise, clear sentence describing the preference.
   - "confidence": Float between 0.0 and 1.0 (only output > 0.8).
   - "scope": "global" or a specific domain (e.g., "frontend", "python").
   - "change_kind": "support", "contradict", "supersede", "constrain", or "none" (How this preference relates to past behavior, usually 'none' for new, 'contradict' if user was angry at AI's previous approach).

Example Output:
[
  {
    "preference_key": "reply_style",
    "preference_claim": "User strictly prefers pure code output without markdown explanations.",
    "confidence": 0.95,
    "scope": "global",
    "change_kind": "contradict"
  }
]
"""


class CognitiveDeriver:
    """Async Dialectic Reasoning Engine for implicit preference extraction."""

    def __init__(self, manager: MemoryManager) -> None:
        self.manager = manager
        self.llm_func = manager._consolidation_llm
        self.graph = manager.graph_store

    async def run_derivation(
        self, session_id: str, chat_id: str, messages: list[dict[str, str]]
    ) -> dict[str, bool | int | str]:
        """Run dialectic reasoning on recent messages and update the vector and graph."""
        if not self.llm_func:
            return {"skipped": True, "reason": "No LLM configured"}

        if not messages:
            return {"skipped": True, "reason": "No messages provided"}

        # Format messages
        formatted = "\\n".join(
            f"[{m.get('role', 'user').upper()}]: {m.get('content', '')}"
            for m in messages[-10:]  # Analyze last 10 messages
        )

        prompt = f"## Recent Conversation\\n\\n{formatted}\\n\\n## Task\\nExtract implicit preferences as JSON array."

        try:
            raw = await self.llm_func(_DERIVER_PROMPT, prompt)

            match = re.search(r"(\\[.*\\])", raw, re.DOTALL)
            if match:
                raw = match.group(1)
            data = json.loads(raw)

            extracted_count = 0
            has_disruptive_change = False
            for item in data:
                confidence = float(item.get("confidence", 0.0))
                if confidence < 0.8:
                    continue

                pref_key = item.get("preference_key", "general_preference")
                pref_claim = item.get("preference_claim", "")
                scope = item.get("scope", "global")
                change_kind = item.get("change_kind", "none")

                if not pref_claim:
                    continue

                if change_kind in ("contradict", "supersede"):
                    has_disruptive_change = True

                await self._store_preference_claim(
                    session_id, chat_id, pref_key, pref_claim, confidence, scope, change_kind
                )
                extracted_count += 1

            return {"success": True, "extracted_count": extracted_count, "has_disruptive_change": has_disruptive_change}

        except Exception as e:
            logger.error("Cognitive derivation failed: %s", e)
            return {"success": False, "error": str(e)}

    async def _store_preference_claim(
        self,
        session_id: str,
        chat_id: str,
        pref_key: str,
        pref_claim: str,
        confidence: float,
        scope: str,
        change_kind: str,
    ) -> None:
        """Store the derived preference as a Claim node in the graph and Dual-Write to Vector."""
        now = datetime.now(UTC)

        from myrm_agent_harness.toolkits.memory._internal.maintenance import (
            _classify_claim_relation,
            _normalize_change_kind,
        )

        # --- B. Vector Dual Write (SemanticMemory) & Profile Entry ---
        from myrm_agent_harness.toolkits.memory.types import SemanticMemory

        normalized_strength = min(confidence, 1.0)
        if change_kind in ("contradict", "supersede"):
            normalized_strength = 1.0

        semantic_mem = SemanticMemory(
            content=f"User preference [{pref_key} in {scope}]: {pref_claim}",
            importance=0.8,
            confidence=confidence,
            source_chat_id=chat_id,
            preference_type="implicit",
            preference_strength=normalized_strength,
            metadata={
                "preference_key": pref_key,
                "scope": scope,
                "change_kind": change_kind,
                "derivation_time": now.isoformat(),
            },
        )

        try:
            # Store via manager to inherit standard namespaces and session limits
            await self.manager.store(semantic_mem, _bypass_approval=True)

            # For core implicit preferences, also dual-write to ProfileEntry for global injection
            if pref_key in ("reply_style", "cognitive_depth", "proactivity"):
                await self.manager.set_profile_attribute(key=pref_key, value=pref_claim)
        except Exception as e:
            logger.warning("Failed to dual-write semantic memory for derived preference: %s", e)

        # --- A. Graph Write (Degradable) ---
        if not self.graph:
            return

        # 1. Create Evidence Node (representing this specific derivation event)
        evidence_id = f"evidence:deriver:{session_id}:{now.timestamp()}"
        evidence_node = await self.graph.get_or_create_node(
            labels=["Evidence"],
            match_keys=["source_memory_id"],
            properties={
                "id": evidence_id,
                "source_memory_id": evidence_id,
                "title": f"Derived Preference: {pref_key}",
                "goal": "Dialectic Reasoning",
                "result": pref_claim,
                "change_kind": _normalize_change_kind(change_kind),
                "key_details": "",
                "source_chat_id": chat_id,
                "channel_id": "cognitive_deriver",
                "freshness_days": 0,
                "primary_namespace": session_id,
            },
        )

        # 2. Get or Create Claim Node
        claim_key_id = f"pref-{pref_key}-{scope}"
        claim_node = await self.graph.get_or_create_node(
            labels=["Claim"],
            match_keys=["primary_namespace", "claim_key"],
            properties={
                "id": f"claim:{session_id}:{claim_key_id}",
                "primary_namespace": session_id,
                "claim_key": claim_key_id,
                "title": f"User Preference: {pref_key}",
                "goal": "Preference",
                "claim_text": pref_claim,
                "change_kind": _normalize_change_kind(change_kind),
                "key_details": "",
                "model_summary": f"Preference [{scope}]: {pref_claim}",
                "confidence": confidence,
                "freshness_days": 0,
                "freshness": "fresh",
                "contradiction_status": ClaimConflictState.NONE.value,
                "contradiction_count": 0,
                "evidence_count": 0,
                "last_result": pref_claim,
                "result_polarity": "neutral",
                "latest_relationship_type": "SUPPORTED_BY",
                "last_evidence_at": now.isoformat(),
                "latest_channel_id": "cognitive_deriver",
                "latest_source_memory_id": evidence_id,
            },
        )

        existing_evidence_count = int(claim_node.properties.get("evidence_count", 0))
        contradiction_count = int(claim_node.properties.get("contradiction_count", 0))

        relationship_type, is_conflicted = _classify_claim_relation(
            existing_goal="Preference",
            existing_result=str(claim_node.properties.get("last_result", "")),
            existing_key_details="",
            existing_polarity="neutral",
            new_goal="Preference",
            new_result=pref_claim,
            new_key_details="",
            new_polarity="neutral",
            existing_evidence_count=existing_evidence_count,
            explicit_change_kind=change_kind,
        )

        if is_conflicted:
            contradiction_count += 1

        updated_contradiction_status = (
            ClaimConflictState.CONFLICTED.value if is_conflicted else ClaimConflictState.NONE.value
        )

        updated_evidence_count = existing_evidence_count + 1

        # 3. Create Relationship
        await self.graph.create_relationship(
            claim_node.id,
            evidence_node.id,
            relationship_type,
            properties={
                "confidence": confidence,
                "freshness_days": 0.0,
            },
        )

        # 4. Update Claim Node
        await self.graph.update_node_properties(
            claim_node.id,
            {
                "claim_text": pref_claim,
                "change_kind": _normalize_change_kind(change_kind),
                "model_summary": f"Preference [{scope}]: {pref_claim}",
                "confidence": confidence,
                "freshness_days": 0,
                "freshness": "fresh",
                "contradiction_status": updated_contradiction_status,
                "contradiction_count": contradiction_count,
                "evidence_count": updated_evidence_count,
                "last_result": pref_claim,
                "latest_relationship_type": relationship_type,
                "last_evidence_at": now.isoformat(),
                "latest_source_memory_id": evidence_id,
            },
        )
