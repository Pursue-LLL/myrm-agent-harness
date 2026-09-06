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


def inject_capacity_signal(
    result: dict[str, object], parent_agent: BaseAgent
) -> dict[str, object]:
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
    total_count = len(results)
    completed_count = sum(1 for item in results if item.get("success") is True)
    failed_count = total_count - completed_count
    all_success = failed_count == 0
    if all_success:
        status = "completed"
    elif completed_count > 0:
        status = "partial_success"
    else:
        status = "failed"

    completeness_ratio = round(completed_count / total_count, 4) if total_count > 0 else 0.0

    failure_reasons: list[str] = []
    missing_tasks: list[dict[str, object]] = []

    for index, item in enumerate(results):
        if item.get("success") is not True:
            err = str(item.get("error") or item.get("reason") or "unknown_failure")
            failure_reasons.append(err)
            task_idx = int(item.get("task_index", index))
            agent_t = str(item.get("agent_type") or "general")
            t_id = str(item.get("task_id") or "") if item.get("task_id") is not None else None
            m_entry: dict[str, object] = {
                "task_index": task_idx,
                "agent_type": agent_t,
                "error": err,
            }
            if t_id:
                m_entry["task_id"] = t_id
            missing_tasks.append(m_entry)

    completeness_warning: str | None = None
    if failed_count > 0:
        missing_summary_items = []
        for m in missing_tasks[:5]:
            t_label = m.get("task_id") or f"task_{m.get('task_index')}"
            a_type = m.get("agent_type")
            err = m.get("error")
            missing_summary_items.append(f"[{t_label}: {a_type} - {err}]")
        if len(missing_tasks) > 5:
            missing_summary_items.append(f"...and {len(missing_tasks) - 5} more")
        missing_summary = ", ".join(missing_summary_items)
        completeness_warning = (
            f"⚠️ FLEET INCOMPLETE: Expected {total_count} subtasks, but {failed_count} failed "
            f"({completeness_ratio:.1%} completed). Missing tasks: {missing_summary}. "
            "Downstream synthesis MUST explicitly disclose these gaps and MUST NOT impersonate a 100% complete dataset!"
        )

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
        "total_count": total_count,
        "completed_count": completed_count,
        "failed_count": failed_count,
        "completeness_ratio": completeness_ratio,
        "failure_reasons": failure_reasons,
        "missing_tasks": missing_tasks,
        "all_success": all_success,
        "partial_success": completed_count > 0 and failed_count > 0,
        "gate_passed": True,
    }
    if completeness_warning is not None:
        summary["completeness_warning"] = completeness_warning
    if handoff_states:
        summary["handoff_states"] = handoff_states
    if all_artifact_refs:
        summary["all_artifact_refs"] = all_artifact_refs
    if all_citations:
        summary["all_citations"] = all_citations
    if all_findings:
        summary["all_findings"] = all_findings

    return summary
