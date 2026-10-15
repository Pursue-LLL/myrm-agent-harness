"""DAG dependency calculation and topological analysis for Multi-Agent Kanban Orchestrator."""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.kanban_orchestrator.types import (
    KanbanCardDTO,
    KanbanCardNotFoundError,
    KanbanDependencyCycleError,
    KanbanLaneEnum,
)


class KanbanTaskDagEngine:
    """Calculates card dependency directed acyclic graphs and triggers auto-unblock events."""

    @staticmethod
    def validate_dependencies(cards: dict[str, KanbanCardDTO]) -> None:
        """Validate that all referenced prerequisite cards exist and no circular dependencies exist."""
        # 1. Existence check
        for card_id, card in cards.items():
            for dep_id in card.depends_on:
                if dep_id == card_id:
                    raise KanbanDependencyCycleError(f"Card '{card_id}' cannot depend on itself.")
                if dep_id not in cards:
                    raise KanbanCardNotFoundError(
                        f"Card '{card_id}' depends on non-existent card '{dep_id}'."
                    )

        # 2. Cycle detection using DFS with recursion stack
        visited: set[str] = set()
        rec_stack: list[str] = []

        def dfs(node: str) -> None:
            visited.add(node)
            rec_stack.append(node)

            for dep in cards[node].depends_on:
                if dep in rec_stack:
                    idx = rec_stack.index(dep)
                    cycle_path = [*rec_stack[idx:], dep]
                    raise KanbanDependencyCycleError(
                        f"Cyclic dependency detected: {' -> '.join(cycle_path)}"
                    )
                if dep not in visited:
                    dfs(dep)

            rec_stack.pop()

        for c_id in cards:
            if c_id not in visited:
                dfs(c_id)

    @staticmethod
    def compute_blocked_status(
        card: KanbanCardDTO,
        all_cards: dict[str, KanbanCardDTO],
    ) -> list[str]:
        """Return the list of prerequisite card IDs that are not yet in the DONE lane."""
        unresolved: list[str] = []
        for dep_id in card.depends_on:
            dep_card = all_cards.get(dep_id)
            if not dep_card or dep_card.lane != KanbanLaneEnum.DONE:
                unresolved.append(dep_id)
        return unresolved

    @staticmethod
    def find_auto_unblockable_downstreams(
        completed_card_id: str,
        all_cards: dict[str, KanbanCardDTO],
    ) -> list[str]:
        """Find blocked downstream cards that can now be auto-unblocked because all prerequisites are DONE."""
        unblockable: list[str] = []

        for card_id, card in all_cards.items():
            if card_id == completed_card_id:
                continue
            if completed_card_id in card.depends_on and card.lane == KanbanLaneEnum.BLOCKED:
                # Check if all other prerequisites are also DONE
                remaining_blocked = [
                    d_id
                    for d_id in card.depends_on
                    if d_id != completed_card_id
                    and (d_id not in all_cards or all_cards[d_id].lane != KanbanLaneEnum.DONE)
                ]
                if not remaining_blocked:
                    unblockable.append(card_id)

        return unblockable

    @staticmethod
    def topological_sort(cards: dict[str, KanbanCardDTO]) -> list[str]:
        """Return list of card IDs sorted in dependency topological execution order."""
        KanbanTaskDagEngine.validate_dependencies(cards)

        in_degree: dict[str, int] = {c_id: len(card.depends_on) for c_id, card in cards.items()}
        # Adjacency list: parent -> children that depend on parent
        dependents_map: dict[str, list[str]] = {c_id: [] for c_id in cards}
        for c_id, card in cards.items():
            for dep_id in card.depends_on:
                dependents_map[dep_id].append(c_id)

        queue: list[str] = [c_id for c_id, deg in in_degree.items() if deg == 0]
        sorted_cards: list[str] = []

        while queue:
            curr = queue.pop(0)
            sorted_cards.append(curr)
            for child in dependents_map.get(curr, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        return sorted_cards
