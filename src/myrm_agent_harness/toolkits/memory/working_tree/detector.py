"""Fast two-stage contradiction and temporal-update detector for evidence nodes.

[INPUT]
- toolkits.memory.working_tree.models::EvidenceNode (POS: 强类型树状工作记忆原子节点)
- toolkits.memory.working_tree.models::ConflictVerdict (POS: 矛盾初筛与仲裁裁决结果)
- toolkits.memory.working_tree.models::ConflictType (POS: 语义冲突与时态演化分类枚举)
- langchain_core.language_models::BaseChatModel (POS: 语言模型统一抽象接口)

[OUTPUT]
- FastContradictionDetector: 双阶段冲突与时态演化检测器（Stage 1 确定性预检 + Stage 2 Fast-LLM 语义仲裁）

[POS]
ReTree 冲突检测引擎。提供秒级实体与否定词初筛及轻量 LLM 语义仲裁，区分直接反驳与时态演化。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .models import ConflictType, ConflictVerdict, EvidenceNode

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


NEGATION_PATTERNS = (
    r"\bnot\b",
    r"\bno longer\b",
    r"\bnever\b",
    r"\bfalse\b",
    r"\bdebunked\b",
    r"\bdisproven\b",
    r"\brefuted\b",
    r"\bincorrect\b",
    r"辟谣",
    r"并非",
    r"并非如此",
    r"不再",
    r"更正",
    r"推翻",
    r"失实",
)

TEMPORAL_PATTERNS = (
    r"\bsince\s+\d{4}\b",
    r"\bas of\s+\d{4}\b",
    r"\blatest\b",
    r"\brecently\b",
    r"\bnow\b",
    r"\bcurrent\b",
    r"\bupgraded to\b",
    r"\bmigrated to\b",
    r"截至",
    r"目前",
    r"最新",
    r"如今",
    r"已升级",
    r"现任",
)

ARBITRATION_SYSTEM_PROMPT = (
    "You are an evidence conflict arbitrator in a deep research agent.\n"
    "Compare the PRIOR verified node with the NEW evidence and determine their logical relation:\n"
    "- CONTRADICTION: Direct factual conflict or mutually exclusive claims for the same subject.\n"
    "- TEMPORAL_UPDATE: Later status, newer date, or newer data superseding earlier outdated info.\n"
    "- COMPLEMENTARY: Consistent, non-conflicting supplementary details or different facets.\n"
    "- NONE: Unrelated facts with no meaningful factual overlap.\n\n"
    "Respond strictly in one line formatted as:\n"
    "VERDICT: <CONTRADICTION|TEMPORAL_UPDATE|COMPLEMENTARY|NONE> | REASON: <brief explanation>"
)


class FastContradictionDetector:
    """Two-stage contradiction detector operating over the EvidenceTree."""

    def __init__(self, arbitrator_llm: BaseChatModel | None = None) -> None:
        self.arbitrator_llm = arbitrator_llm

    def check_conflict(
        self,
        new_claim: str,
        new_summary: str,
        existing_nodes: list[EvidenceNode],
        new_content_hash: str = "",
    ) -> ConflictVerdict:
        """Evaluate whether new evidence conflicts with any existing active node."""
        if not existing_nodes:
            return ConflictVerdict(conflict_type=ConflictType.NONE)

        # Stage 1: Fast deterministic screening
        combined_text = f"{new_claim} {new_summary}".lower()

        # Check for identical hash duplicate
        if new_content_hash:
            for node in existing_nodes:
                if node.source.content_hash and node.source.content_hash == new_content_hash:
                    return ConflictVerdict(
                        conflict_type=ConflictType.NONE,
                        conflicting_node_id=node.node_id,
                        reason="Exact fingerprint duplicate",
                    )

        has_negation = any(re.search(pat, combined_text, re.IGNORECASE) for pat in NEGATION_PATTERNS)
        has_temporal = any(re.search(pat, combined_text, re.IGNORECASE) for pat in TEMPORAL_PATTERNS)

        candidate_node = self._find_candidate_node(new_claim, new_summary, existing_nodes, has_negation)
        if not candidate_node:
            return ConflictVerdict(conflict_type=ConflictType.NONE)

        # Stage 2: Arbitration (heuristic if no LLM provided, or fast LLM invoke)
        if not self.arbitrator_llm:
            if has_temporal and not has_negation:
                return ConflictVerdict(
                    conflict_type=ConflictType.TEMPORAL_UPDATE,
                    conflicting_node_id=candidate_node.node_id,
                    reason=f"Temporal keywords detected updating node {candidate_node.node_id}",
                    confidence=0.85,
                )
            if has_negation:
                return ConflictVerdict(
                    conflict_type=ConflictType.CONTRADICTION,
                    conflicting_node_id=candidate_node.node_id,
                    reason=f"Explicit negation pattern contradictory to node {candidate_node.node_id}",
                    confidence=0.90,
                )
            return ConflictVerdict(
                conflict_type=ConflictType.COMPLEMENTARY,
                conflicting_node_id=candidate_node.node_id,
                reason="Shared entities with consistent non-contradictory claims",
                confidence=0.75,
            )

        return self._arbitrate_with_llm(new_claim, new_summary, candidate_node)

    def _find_candidate_node(
        self,
        new_claim: str,
        new_summary: str,
        existing_nodes: list[EvidenceNode],
        has_negation: bool,
    ) -> EvidenceNode | None:
        """Screen existing nodes for shared entities, claim overlap, or metric collisions."""
        new_words = set(re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", new_claim.lower()))
        new_summary_tokens = set(re.findall(r"\b[a-zA-Z_]+\b", new_summary.lower()))

        for node in existing_nodes:
            existing_entities = {e.lower() for e in node.bounded_summary.key_entities}
            existing_claim_words = set(re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", node.claim.lower()))
            shared = (existing_entities | existing_claim_words).intersection(new_words)
            colliding_keys = {k.lower() for k in node.bounded_summary.key_metrics}.intersection(new_summary_tokens)
            if shared or colliding_keys or has_negation:
                return node
        return None

    async def acheck_conflict(
        self,
        new_claim: str,
        new_summary: str,
        existing_nodes: list[EvidenceNode],
        new_content_hash: str = "",
    ) -> ConflictVerdict:
        """Asynchronously evaluate whether new evidence conflicts with any existing active node."""
        if not existing_nodes:
            return ConflictVerdict(conflict_type=ConflictType.NONE)

        combined_text = f"{new_claim} {new_summary}".lower()

        if new_content_hash:
            for node in existing_nodes:
                if node.source.content_hash and node.source.content_hash == new_content_hash:
                    return ConflictVerdict(
                        conflict_type=ConflictType.NONE,
                        conflicting_node_id=node.node_id,
                        reason="Exact fingerprint duplicate",
                    )

        has_negation = any(re.search(pat, combined_text, re.IGNORECASE) for pat in NEGATION_PATTERNS)
        has_temporal = any(re.search(pat, combined_text, re.IGNORECASE) for pat in TEMPORAL_PATTERNS)

        candidate_node = self._find_candidate_node(new_claim, new_summary, existing_nodes, has_negation)
        if not candidate_node:
            return ConflictVerdict(conflict_type=ConflictType.NONE)

        if not self.arbitrator_llm:
            if has_temporal and not has_negation:
                return ConflictVerdict(
                    conflict_type=ConflictType.TEMPORAL_UPDATE,
                    conflicting_node_id=candidate_node.node_id,
                    reason=f"Temporal keywords detected updating node {candidate_node.node_id}",
                    confidence=0.85,
                )
            if has_negation:
                return ConflictVerdict(
                    conflict_type=ConflictType.CONTRADICTION,
                    conflicting_node_id=candidate_node.node_id,
                    reason=f"Explicit negation pattern contradictory to node {candidate_node.node_id}",
                    confidence=0.90,
                )
            return ConflictVerdict(
                conflict_type=ConflictType.COMPLEMENTARY,
                conflicting_node_id=candidate_node.node_id,
                reason="Shared entities with consistent non-contradictory claims",
                confidence=0.75,
            )

        return await self._aarbitrate_with_llm(new_claim, new_summary, candidate_node)

    def _parse_verdict(self, content: str, candidate_node: EvidenceNode) -> ConflictVerdict:
        """Parse raw LLM response into a strongly typed ConflictVerdict."""
        match = re.search(r"VERDICT:\s*([A-Z_]+)(?:\s*\|\s*REASON:\s*(.*))?", content, re.IGNORECASE)
        if match:
            verdict_str = match.group(1).upper()
            reason = match.group(2).strip() if match.group(2) else "LLM arbitration"
            verdict_map = {
                "CONTRADICTION": ConflictType.CONTRADICTION,
                "TEMPORAL_UPDATE": ConflictType.TEMPORAL_UPDATE,
                "COMPLEMENTARY": ConflictType.COMPLEMENTARY,
                "NONE": ConflictType.NONE,
            }
            return ConflictVerdict(
                conflict_type=verdict_map.get(verdict_str, ConflictType.NONE),
                conflicting_node_id=candidate_node.node_id,
                reason=reason,
                confidence=0.95,
            )
        return ConflictVerdict(
            conflict_type=ConflictType.NONE,
            conflicting_node_id=candidate_node.node_id,
            reason="Arbitration fallback to neutral",
        )

    def _arbitrate_with_llm(
        self, new_claim: str, new_summary: str, candidate_node: EvidenceNode
    ) -> ConflictVerdict:
        """Invoke fast lightweight LLM synchronously to classify contradiction vs temporal update."""
        if not self.arbitrator_llm:
            return ConflictVerdict(conflict_type=ConflictType.NONE)

        from langchain_core.messages import HumanMessage, SystemMessage

        user_msg = (
            f"PRIOR NODE [{candidate_node.node_id}]: {candidate_node.bounded_summary.summary}\n"
            f"NEW EVIDENCE: {new_claim} - {new_summary}"
        )
        try:
            resp = self.arbitrator_llm.invoke(
                [SystemMessage(content=ARBITRATION_SYSTEM_PROMPT), HumanMessage(content=user_msg)]
            )
            return self._parse_verdict(str(resp.content).strip(), candidate_node)
        except Exception:
            return ConflictVerdict(
                conflict_type=ConflictType.NONE,
                conflicting_node_id=candidate_node.node_id,
                reason="Arbitration invocation failed",
            )

    async def _aarbitrate_with_llm(
        self, new_claim: str, new_summary: str, candidate_node: EvidenceNode
    ) -> ConflictVerdict:
        """Invoke fast lightweight LLM asynchronously to classify contradiction vs temporal update."""
        if not self.arbitrator_llm:
            return ConflictVerdict(conflict_type=ConflictType.NONE)

        from langchain_core.messages import HumanMessage, SystemMessage

        user_msg = (
            f"PRIOR NODE [{candidate_node.node_id}]: {candidate_node.bounded_summary.summary}\n"
            f"NEW EVIDENCE: {new_claim} - {new_summary}"
        )
        try:
            resp = await self.arbitrator_llm.ainvoke(
                [SystemMessage(content=ARBITRATION_SYSTEM_PROMPT), HumanMessage(content=user_msg)]
            )
            return self._parse_verdict(str(resp.content).strip(), candidate_node)
        except Exception:
            return ConflictVerdict(
                conflict_type=ConflictType.NONE,
                conflicting_node_id=candidate_node.node_id,
                reason="Arbitration invocation failed",
            )
