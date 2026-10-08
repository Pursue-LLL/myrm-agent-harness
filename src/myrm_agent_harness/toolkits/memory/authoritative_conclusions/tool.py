# [POS]: myrm_agent_harness.toolkits.memory.authoritative_conclusions.tool
# [INPUT]: models.py, store.py
# [OUTPUT]: AuthoritativeConclusionToolSuite, memory_conclude_tool

"""Callable agent meta-tool for explicit authoritative conclusions and lifecycle audit.

P0 delivery for Item 111 in topic_01 memory roadmap.
Equips agents with first-class decision declaration, listing, deprecation,
and physical deletion capabilities (conclude tool protocol).

[INPUT]
- toolkits.memory.authoritative_conclusions.models::ConclusionStatus, ConclusionToolAction (POS: Domain models
  for Explicit Authoritative Conclusions and Audit Tooling Suite.)
- toolkits.memory.authoritative_conclusions.store::AuthoritativeConclusionStore (POS: In-memory and indexed
  repository for authoritative conclusions and audit trails.)

[OUTPUT]
- AuthoritativeConclusionToolSuite: Tool suite providing agent-facing memory_conclude_tool execution.
- memory_conclude_tool(): Callable tool entrypoint exposed to LLM agents.

[POS]
Callable agent meta-tool for explicit authoritative conclusions and lifecycle audit.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.toolkits.memory.authoritative_conclusions.models import (
    ConclusionStatus,
    ConclusionToolAction,
)
from myrm_agent_harness.toolkits.memory.authoritative_conclusions.store import (
    AuthoritativeConclusionStore,
)

logger = logging.getLogger(__name__)


class AuthoritativeConclusionToolSuite:
    """Tool suite providing agent-facing memory_conclude_tool execution."""

    def __init__(self, store: AuthoritativeConclusionStore | None = None) -> None:
        self._store = store or AuthoritativeConclusionStore()

    @property
    def store(self) -> AuthoritativeConclusionStore:
        """Underlying authoritative conclusion store."""
        return self._store

    def execute(
        self,
        action: str,
        content: str = "",
        peer_id: str = "current_agent",
        scope_tag: str = "general",
        conclusion_id: str | None = None,
        keyword: str | None = None,
        rationale: str = "",
    ) -> str:
        """Execute conclusion lifecycle action and return formatted confirmation."""
        action_clean = action.strip().lower()

        if action_clean == ConclusionToolAction.WRITE.value:
            if not content.strip():
                return "Error: 'content' parameter is required when declaring a conclusion."
            conc = self._store.write_conclusion(
                content=content,
                peer_id=peer_id,
                scope_tag=scope_tag,
                conclusion_id=conclusion_id,
                operator_peer_id=peer_id,
                auto_confirm=True,
                rationale=rationale,
            )
            return (
                f"Successfully declared authoritative conclusion [{conc.conclusion_id}] "
                f"for peer @{conc.peer_id} under scope '{conc.scope_tag}':\n"
                f"\"{conc.content}\""
            )

        elif action_clean == ConclusionToolAction.LIST.value:
            results = self._store.list_conclusions(
                peer_id=peer_id if peer_id != "current_agent" and peer_id else None,
                status=ConclusionStatus.CONFIRMED,
                scope_tag=scope_tag if scope_tag != "general" else None,
                keyword=keyword,
            )
            if not results:
                return "No matching active authoritative conclusions found."
            lines = [f"Found {len(results)} authoritative conclusions:"]
            for r in results:
                lines.append(
                    f"- [{r.conclusion_id}] (@{r.peer_id}, scope={r.scope_tag}): {r.content}"
                )
            return "\n".join(lines)

        elif action_clean == ConclusionToolAction.DEPRECATE.value:
            if not conclusion_id:
                return "Error: 'conclusion_id' parameter is required to deprecate a conclusion."
            deprecated = self._store.deprecate_conclusion(
                conclusion_id=conclusion_id,
                operator_peer_id=peer_id,
                rationale=rationale or "Explicit deprecation via agent tool",
            )
            if not deprecated:
                return f"Error: Conclusion '{conclusion_id}' not found."
            return (
                f"Successfully deprecated conclusion [{deprecated.conclusion_id}]. "
                f"Audit trail recorded (reason: {rationale or 'N/A'})."
            )

        elif action_clean == ConclusionToolAction.DELETE.value:
            if not conclusion_id:
                return "Error: 'conclusion_id' parameter is required to physically delete a conclusion."
            deleted = self._store.delete_conclusion(
                conclusion_id=conclusion_id,
                operator_peer_id=peer_id,
                rationale=rationale or "PII removal/policy erasure via agent tool",
            )
            if not deleted:
                return f"Error: Conclusion '{conclusion_id}' not found."
            return (
                f"Successfully erased conclusion [{conclusion_id}] for policy compliance. "
                f"Deletion audit logged."
            )

        else:
            return (
                f"Error: Unknown action '{action}'. Valid actions are: "
                f"write, list, deprecate, delete."
            )


def memory_conclude_tool(
    action: str,
    content: str = "",
    peer_id: str = "current_agent",
    scope_tag: str = "general",
    conclusion_id: str | None = None,
    keyword: str | None = None,
    rationale: str = "",
    *,
    suite: AuthoritativeConclusionToolSuite | None = None,
) -> str:
    """Callable tool entrypoint exposed to LLM agents."""
    active_suite = suite or AuthoritativeConclusionToolSuite()
    return active_suite.execute(
        action=action,
        content=content,
        peer_id=peer_id,
        scope_tag=scope_tag,
        conclusion_id=conclusion_id,
        keyword=keyword,
        rationale=rationale,
    )
