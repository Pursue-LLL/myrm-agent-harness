"""Public batch summary helpers for parallel subagent execution.

[INPUT]
- results: list[dict[str, object]] from parallel task executions
- parent_agent: BaseAgent for capacity snapshot

[OUTPUT]
- batch_summary: dict containing status, handoff_states, all_artifact_refs, all_citations, all_findings with evidence lineage
- inject_capacity_signal: dict updated with active subagents and remaining slot metrics

[POS]
Parallel execution subsystem summary and capacity aggregation layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent


def inject_capacity_signal(result: dict[str, object], parent_agent: BaseAgent) -> dict[str, object]:
    """Inject delegation capacity info into tool output for LLM decision context."""
    try:
        manager = parent_agent._subagent_manager
        snap = manager.get_capacity_snapshot()
        result["system_state"] = {
            "active_subagents": f"{snap.active_children}/{snap.max_children}",
            "remaining_slots": snap.remaining_slots,
            "descendants_spawned": f"{snap.spawned_descendants}/{snap.max_descendants}",
            "remaining_descendants": snap.remaining_descendants,
        }
    except Exception:
        pass
    return result


def batch_summary(results: list[dict[str, object]]) -> dict[str, object]:
    """Aggregate per-task results into a resume-friendly batch summary with structured handover aggregation."""
    completed_count = sum(1 for item in results if item.get("success") is True)
    failed_count = len(results) - completed_count
    all_success = failed_count == 0
    if all_success:
        status = "completed"
    elif completed_count > 0:
        status = "partial_success"
    else:
        status = "failed"
    failure_reasons = [
        str(item.get("error") or item.get("reason") or "unknown_failure")
        for item in results
        if item.get("success") is not True
    ]
    handoff_states: list[dict[str, object]] = []
    all_artifact_refs: list[str] = []
    all_citations: list[str] = []
    all_findings: list[dict[str, str]] = []

    for item in results:
        ho = item.get("handover_state")
        if isinstance(ho, dict):
            handoff_states.append(ho)
            refs = ho.get("artifact_refs")
            if isinstance(refs, list):
                for r in refs:
                    if isinstance(r, str) and r not in all_artifact_refs:
                        all_artifact_refs.append(r)
            cits = ho.get("citations")
            if isinstance(cits, list):
                for c in cits:
                    if isinstance(c, str) and c not in all_citations:
                        all_citations.append(c)
            task_id = str(item.get("task_id") or "")
            agent_type = str(item.get("agent_type") or "")
            f_list = ho.get("findings")
            if isinstance(f_list, list):
                for f in f_list:
                    if isinstance(f, dict):
                        f_entry = {k: str(v) for k, v in f.items()}
                        if task_id and "source_task_id" not in f_entry:
                            f_entry["source_task_id"] = task_id
                        if agent_type and "agent_type" not in f_entry:
                            f_entry["agent_type"] = agent_type
                        all_findings.append(f_entry)

    summary: dict[str, object] = {
        "success": all_success,
        "status": status,
        "total_count": len(results),
        "completed_count": completed_count,
        "failed_count": failed_count,
        "failure_reasons": failure_reasons,
        "all_success": all_success,
        "partial_success": completed_count > 0 and failed_count > 0,
    }
    if handoff_states:
        summary["handoff_states"] = handoff_states
    if all_artifact_refs:
        summary["all_artifact_refs"] = all_artifact_refs
    if all_citations:
        summary["all_citations"] = all_citations
    if all_findings:
        summary["all_findings"] = all_findings

    return summary
