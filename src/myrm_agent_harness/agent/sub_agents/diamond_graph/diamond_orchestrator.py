"""Diamond Topology DAG orchestrator with False-Dependency Pruning and Dead-Node Census Sentinel.

[INPUT]
- time
- uuid
- types

[OUTPUT]
- DiamondGraphOrchestrator

[POS]
Diamond Topology DAG orchestrator with False-Dependency Pruning and Dead-Node Census Sentinel.

"""

import time
import uuid
from .types import CensusStatus, DiamondNode, DiamondStage


class DiamondGraphOrchestrator:
    """Manages the 3-stage Diamond Topology (Fan-out -> Reduce -> Synthesize)."""

    def __init__(self) -> None:
        self._nodes: dict[str, DiamondNode] = {}
        self._pipeline_id: str = f"diamond-{uuid.uuid4().hex[:8]}"

    @property
    def pipeline_id(self) -> str:
        return self._pipeline_id

    def create_diamond_pipeline(
        self,
        goal: str,
        fan_out_specs: list[dict[str, str]],
    ) -> tuple[list[DiamondNode], DiamondNode, DiamondNode]:
        """Construct standard 3-tier diamond: N fan_out -> 1 reduce -> 1 synthesize."""
        fan_out_nodes: list[DiamondNode] = []
        fan_out_ids: list[str] = []

        for i, spec in enumerate(fan_out_specs):
            nid = spec.get("node_id") or f"fan-{i+1}-{uuid.uuid4().hex[:6]}"
            node = DiamondNode(
                node_id=nid,
                title=spec.get("title", f"Explore Branch {i+1}"),
                stage=DiamondStage.FAN_OUT,
                depends_on=[],
                payload=dict(spec),
                status="pending",
            )
            self._nodes[nid] = node
            fan_out_nodes.append(node)
            fan_out_ids.append(nid)

        reduce_id = f"reduce-{uuid.uuid4().hex[:6]}"
        reduce_node = DiamondNode(
            node_id=reduce_id,
            title="Deterministic Map-Reduce Deduplicator",
            stage=DiamondStage.REDUCE,
            depends_on=list(fan_out_ids),
            payload={"goal": goal},
            status="pending",
        )
        self._nodes[reduce_id] = reduce_node

        synth_id = f"synth-{uuid.uuid4().hex[:6]}"
        synth_node = DiamondNode(
            node_id=synth_id,
            title="Top-Tier High Quality Synthesis",
            stage=DiamondStage.SYNTHESIZE,
            depends_on=[reduce_id],
            payload={"goal": goal},
            status="pending",
        )
        self._nodes[synth_id] = synth_node

        return fan_out_nodes, reduce_node, synth_node

    def prune_false_dependencies(self) -> list[tuple[str, str]]:
        """Static analysis algorithm: strip artificial serialized arrows between fan-out nodes."""
        pruned_edges: list[tuple[str, str]] = []
        fan_nodes = [n for n in self._nodes.values() if n.stage == DiamondStage.FAN_OUT]

        for node in fan_nodes:
            new_deps: list[str] = []
            for dep_id in node.depends_on:
                dep_node = self._nodes.get(dep_id)
                # Fan-out nodes should be concurrent; cross fan-out edges without data causality are pruned
                if dep_node and dep_node.stage == DiamondStage.FAN_OUT:
                    pruned_edges.append((dep_id, node.node_id))
                    node.is_pruned = True
                else:
                    new_deps.append(dep_id)
            node.depends_on = new_deps

        return pruned_edges

    def dispatch_fan_out(self) -> CensusStatus:
        """Dispatch all pending fan-out branches concurrently."""
        dispatched = 0
        for node in self._nodes.values():
            if node.stage == DiamondStage.FAN_OUT and node.status in ("pending", "failed"):
                node.status = "running"
                dispatched += 1

        return self.check_census()

    def record_node_completion(
        self,
        node_id: str,
        output_artifact: str,
        cot_reasoning_internal: str | None = None,
        success: bool = True,
    ) -> DiamondNode:
        """Record node outcome, storing CoT internally but strictly isolated from auditors."""
        node = self._nodes.get(node_id)
        if not node:
            raise ValueError(f"Node {node_id} not found")

        node.status = "completed" if success else "failed"
        node.output_artifact = output_artifact
        node.cot_reasoning_internal = cot_reasoning_internal
        return node

    def check_census(self) -> CensusStatus:
        """Dead-Node Census Sentinel: verify exact response count against dispatch."""
        fan_nodes = [n for n in self._nodes.values() if n.stage == DiamondStage.FAN_OUT]
        dispatched_count = len(fan_nodes)
        completed = [n for n in fan_nodes if n.status == "completed"]
        received_count = len(completed)

        missing: list[str] = [n.node_id for n in fan_nodes if n.status != "completed"]
        is_healthy = received_count == dispatched_count

        return CensusStatus(
            dispatched_count=dispatched_count,
            received_count=received_count,
            missing_nodes=missing,
            is_healthy=is_healthy,
        )

    def retry_dead_nodes(self) -> list[str]:
        """Pinpoint missing or failed fan-out nodes and retry them immediately."""
        census = self.check_census()
        retried: list[str] = []

        for nid in census.missing_nodes:
            node = self._nodes.get(nid)
            if node:
                node.status = "running"
                node.output_artifact = None
                retried.append(nid)

        return retried

    def execute_deterministic_reduce(self) -> str:
        """Deterministic 0-token reduction: sorts, deduplicates, and aggregates fan-out outputs."""
        census = self.check_census()
        if not census.is_healthy:
            raise RuntimeError(
                f"Census failure: missing {len(census.missing_nodes)} fan-out branches. All nodes must report before reduce."
            )

        fan_nodes = sorted(
            [n for n in self._nodes.values() if n.stage == DiamondStage.FAN_OUT],
            key=lambda n: n.node_id,
        )

        seen_lines: set[str] = set()
        deduped_entries: list[str] = []

        for node in fan_nodes:
            raw_output = node.output_artifact or ""
            lines = raw_output.strip().split("\n")
            filtered_lines: list[str] = []
            for line in lines:
                norm = line.strip()
                if norm and norm not in seen_lines:
                    seen_lines.add(norm)
                    filtered_lines.append(norm)

            if filtered_lines:
                deduped_entries.append(
                    f"### Branch [{node.node_id}] {node.title}\n" + "\n".join(filtered_lines)
                )

        reduced_content = "\n\n".join(deduped_entries)

        # Update the REDUCE node
        reduce_node = next((n for n in self._nodes.values() if n.stage == DiamondStage.REDUCE), None)
        if reduce_node:
            reduce_node.status = "completed"
            reduce_node.output_artifact = reduced_content

        return reduced_content

    def execute_synthesis(self, summary_prefix: str = "Consolidated Architecture Synthesis:\n") -> str:
        """Complete the top tier synthesize stage with consolidated findings."""
        reduce_node = next((n for n in self._nodes.values() if n.stage == DiamondStage.REDUCE), None)
        synth_node = next((n for n in self._nodes.values() if n.stage == DiamondStage.SYNTHESIZE), None)

        if not reduce_node or reduce_node.status != "completed":
            raise RuntimeError("Reduce stage must be completed before synthesis")

        reduced_data = reduce_node.output_artifact or ""
        synthesized_artifact = f"{summary_prefix}{reduced_data}\n\n[End of Synthesis]"

        if synth_node:
            synth_node.status = "completed"
            synth_node.output_artifact = synthesized_artifact

        return synthesized_artifact

    def get_nodes(self) -> list[DiamondNode]:
        """Return all nodes in the diamond DAG."""
        return list(self._nodes.values())
