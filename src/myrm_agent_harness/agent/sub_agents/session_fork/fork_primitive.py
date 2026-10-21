"""Deterministic subagent session fork primitive conforming to Pi Harness v2 (§17).

[INPUT]
- parent_session_id and tool_call_id
- fork scope (branch or tree) and parent nodes snapshot

[OUTPUT]
- DeterministicSessionForkManager coordinating safe fork & replay reattach
"""

from __future__ import annotations

import hashlib
import threading
import time

from myrm_agent_harness.agent.sub_agents.session_fork.types import (
    ChildSessionLink,
    ForkConflictError,
    ForkedSessionNode,
    ForkResult,
    ForkScope,
)


class DeterministicSessionForkManager:
    """Manages deterministic subagent session derivation and safe replay reattachment.

    Core guarantees:
    1. Deterministic Child ID: derived as f(parentSessionId, toolCallId).
    2. Safe Replay Reattach: repeated tool calls with identical IDs reattach to the
       existing child session instead of spawning duplicate twins.
    3. Scope Isolation: repo.fork(scope=branch|tree) copies entry history only,
       omitting active queues/operations to maintain an idle initial state.
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._links: dict[str, ChildSessionLink] = {}
        self._child_nodes: dict[str, list[ForkedSessionNode]] = {}

    @staticmethod
    def derive_child_session_id(parent_session_id: str, tool_call_id: str) -> str:
        """Deterministically derive a child session ID from parent and tool invocation."""
        raw_key = f"{parent_session_id}::{tool_call_id}".encode()
        digest = hashlib.sha256(raw_key).hexdigest()[:16]
        return f"child-{digest}"

    def fork_child_session(
        self,
        parent_session_id: str,
        tool_call_id: str,
        scope: ForkScope = ForkScope.BRANCH,
        parent_nodes: list[ForkedSessionNode] | None = None,
        target_leaf_id: str | None = None,
    ) -> ForkResult:
        """Fork a child session or safely reattach if it already exists."""
        child_id = self.derive_child_session_id(parent_session_id, tool_call_id)

        with self._lock:
            # Safe replay detection: if already spawned, reattach
            if child_id in self._links:
                existing_link = self._links[child_id]
                if (
                    existing_link.parent_session_id != parent_session_id
                    or existing_link.tool_call_id != tool_call_id
                ):
                    raise ForkConflictError(
                        f"Deterministic conflict: existing child session '{child_id}' "
                        f"belongs to parent '{existing_link.parent_session_id}', "
                        f"attempted fork from '{parent_session_id}'"
                    )

                existing_link.reattach_count += 1
                existing_link.last_attached_at = time.time()
                nodes = self._child_nodes.get(child_id, [])
                root_id = nodes[0].node_id if nodes else "root"
                leaf_id = nodes[-1].node_id if nodes else "root"

                return ForkResult(
                    child_session_id=child_id,
                    parent_session_id=parent_session_id,
                    tool_call_id=tool_call_id,
                    is_reattached=True,
                    fork_scope=existing_link.fork_scope,
                    copied_nodes_count=len(nodes),
                    root_node_id=root_id,
                    leaf_node_id=leaf_id,
                )

            # Fresh fork execution
            source_nodes = list(parent_nodes) if parent_nodes else []
            if not source_nodes:
                # Provide a synthetic root node if parent nodes not supplied
                source_nodes = [
                    ForkedSessionNode(
                        node_id="root",
                        parent_id=None,
                        node_type="root",
                        content="Initial session root",
                        created_at=time.time(),
                        metadata={"origin": "default"},
                    )
                ]

            copied_nodes: list[ForkedSessionNode]
            if scope == ForkScope.TREE:
                # Copy entire shared tree entries
                copied_nodes = list(source_nodes)
            else:
                # Branch scope: trace lineage from target_leaf back to root
                node_map: dict[str, ForkedSessionNode] = {
                    node.node_id: node for node in source_nodes
                }
                current_leaf = target_leaf_id or source_nodes[-1].node_id
                lineage: list[ForkedSessionNode] = []
                curr: str | None = current_leaf
                visited: set[str] = set()

                while curr and curr in node_map and curr not in visited:
                    visited.add(curr)
                    node = node_map[curr]
                    lineage.append(node)
                    curr = node.parent_id

                if not lineage:
                    lineage = [source_nodes[0]]
                lineage.reverse()  # Order from root to leaf
                copied_nodes = lineage

            now = time.time()
            link = ChildSessionLink(
                child_session_id=child_id,
                parent_session_id=parent_session_id,
                tool_call_id=tool_call_id,
                fork_scope=scope,
                created_at=now,
                reattach_count=0,
                last_attached_at=now,
            )

            self._links[child_id] = link
            self._child_nodes[child_id] = copied_nodes

            root_id = copied_nodes[0].node_id
            leaf_id = copied_nodes[-1].node_id

            return ForkResult(
                child_session_id=child_id,
                parent_session_id=parent_session_id,
                tool_call_id=tool_call_id,
                is_reattached=False,
                fork_scope=scope,
                copied_nodes_count=len(copied_nodes),
                root_node_id=root_id,
                leaf_node_id=leaf_id,
            )

    def get_child_session(self, child_session_id: str) -> ChildSessionLink | None:
        """Retrieve the session linkage metadata for a child session."""
        with self._lock:
            return self._links.get(child_session_id)

    def get_child_nodes(self, child_session_id: str) -> list[ForkedSessionNode]:
        """Retrieve copied nodes belonging to a forked child session."""
        with self._lock:
            return list(self._child_nodes.get(child_session_id, []))

    def list_children_for_parent(self, parent_session_id: str) -> list[ChildSessionLink]:
        """List all child sessions deterministically forked by a parent."""
        with self._lock:
            return [
                link
                for link in self._links.values()
                if link.parent_session_id == parent_session_id
            ]

    def reset(self) -> None:
        """Reset internal store."""
        with self._lock:
            self._links.clear()
            self._child_nodes.clear()
