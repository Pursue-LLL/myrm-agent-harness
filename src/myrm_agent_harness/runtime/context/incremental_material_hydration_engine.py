"""Incremental material hydration and project resumption engine.

Extracts semantic diffs (new requirements, modified constraints, deprecations)
from newly injected documents, and synthesizes continuous resumption packages.

[INPUT]
- runtime.context.project_milestone_tracker::ProjectMilestoneTracker (POS: Project milestone tracker
  managing multi-phase project checkpoints.)
- runtime.context.project_milestone_types::IncrementalMaterialUpdate, ProjectResumptionPackage (POS: Data
  contracts for long-horizon project milestone checkpoints and resumption.)

[OUTPUT]
- IncrementalMaterialHydrationEngine: Engine extracting material deltas and synthesizing long-horizon
  resumption context.

[POS]
Incremental material hydration and project resumption engine.
"""

from __future__ import annotations

import re
import time
import uuid

from myrm_agent_harness.runtime.context.project_milestone_tracker import (
    ProjectMilestoneTracker,
)
from myrm_agent_harness.runtime.context.project_milestone_types import (
    IncrementalMaterialUpdate,
    ProjectResumptionPackage,
)

_NEW_REQ_PATTERNS: tuple[str, ...] = (
    "新增",
    "补充需求",
    "需要支持",
    "新特性",
    "add requirement",
    "feature:",
    "new:",
)
_MODIFIED_PATTERNS: tuple[str, ...] = (
    "修改为",
    "调整为",
    "变更",
    "限制为",
    "更新为",
    "modify",
    "update constraint",
    "change:",
)
_DEPRECATED_PATTERNS: tuple[str, ...] = (
    "废弃",
    "不再支持",
    "移除",
    "停止使用",
    "deprecate",
    "remove",
    "obsolete",
)


class IncrementalMaterialHydrationEngine:
    """Engine extracting material deltas and synthesizing long-horizon resumption context."""

    def extract_incremental_diff(
        self,
        raw_text: str,
        source_name: str,
    ) -> IncrementalMaterialUpdate:
        """Parse raw injected material and isolate additions, modifications, and deprecations."""
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.splitlines()]
        clean_lines = [line for line in lines if len(line) >= 4]

        new_reqs: list[str] = []
        mod_constraints: list[str] = []
        deprecated: list[str] = []

        for line in clean_lines:
            lower = line.lower()
            if any(p in lower for p in _DEPRECATED_PATTERNS):
                deprecated.append(line[:160])
            elif any(p in lower for p in _MODIFIED_PATTERNS):
                mod_constraints.append(line[:160])
            elif any(p in lower for p in _NEW_REQ_PATTERNS):
                new_reqs.append(line[:160])

        return IncrementalMaterialUpdate(
            material_id=f"mat_{uuid.uuid4().hex[:8]}",
            source_name=source_name,
            new_requirements=tuple(new_reqs),
            modified_constraints=tuple(mod_constraints),
            deprecated_items=tuple(deprecated),
            injected_at=time.time(),
        )

    def hydrate_material(
        self,
        project_id: str,
        raw_material: str,
        source_name: str,
        tracker: ProjectMilestoneTracker,
    ) -> IncrementalMaterialUpdate:
        """Extract diff from raw material and register it within the project tracker."""
        diff = self.extract_incremental_diff(raw_material, source_name)
        tracker.attach_material_update(project_id, diff)
        return diff

    def synthesize_resumption_package(
        self,
        project_id: str,
        tracker: ProjectMilestoneTracker,
        custom_guidance: str | None = None,
    ) -> ProjectResumptionPackage:
        """Synthesize zero-drift resumption prompt and project progress panorama."""
        latest_cp = tracker.get_latest_milestone(project_id)
        if latest_cp is None:
            # Fallback initialization for uninitialized project
            latest_cp = tracker.init_project(project_id)

        phase = latest_cp.phase
        ready_ids = tracker.compute_ready_todos(project_id)
        pending_todos = [t for t in latest_cp.pending_todos if t.status == "pending"]

        panorama_lines: list[str] = [
            f"=== 项目全景卡 (Project Panorama): {project_id} ===",
            f"当前所处里程碑阶段: {phase.value.upper()}",
            f"已封板里程碑数量: {len(latest_cp.completed_milestones)} 项",
            f"有效不可逆架构决策: {len(latest_cp.active_decisions)} 项",
            f"待办任务总数: {len(pending_todos)} 项 | 拓扑无阻塞就绪项: {len(ready_ids)} 项",
            f"交付物产出文件: {len(latest_cp.deliverable_files)} 个",
        ]
        panorama_summary = "\n".join(panorama_lines)

        # Build resumption prompt with zero-drift guarantees
        prompt_sections: list[str] = [
            f"# 项目持续跟踪与无损续作上下文 [{project_id}]",
            "",
            "你正在继续跟进一个严肃的长程工程项目。请基于既有决策与当前拓扑就绪任务推进，严禁偏离已确立的架构基线。",
            "",
            "## 1. 当前里程碑阶段",
            f"- 阶段: `{phase.value}`",
        ]

        if latest_cp.active_decisions:
            prompt_sections.append("")
            prompt_sections.append("## 2. 关键架构与业务决策（不可逆基线）")
            for idx, dec in enumerate(latest_cp.active_decisions[:6], 1):
                prompt_sections.append(f"- [{idx}] **{dec.title}**: {dec.rationale}")

        if latest_cp.material_history:
            recent_mat = latest_cp.material_history[-1]
            prompt_sections.append("")
            prompt_sections.append(f"## 3. 最新增量注入材料 [{recent_mat.source_name}]")
            if recent_mat.new_requirements:
                prompt_sections.append(f"- **新增需求**: {'; '.join(recent_mat.new_requirements[:4])}")
            if recent_mat.modified_constraints:
                prompt_sections.append(f"- **约束变更**: {'; '.join(recent_mat.modified_constraints[:4])}")
            if recent_mat.deprecated_items:
                prompt_sections.append(f"- **废弃声明**: {'; '.join(recent_mat.deprecated_items[:4])}")

        prompt_sections.append("")
        prompt_sections.append("## 4. 就绪任务与下一步建议")
        if ready_ids:
            ready_items = [t for t in pending_todos if t.todo_id in ready_ids]
            for t in ready_items[:5]:
                prompt_sections.append(f"- 🚀 **就绪待办 [{t.todo_id}]**: {t.title} (优先级: {t.priority})")
        else:
            prompt_sections.append("- 当前无待处理的就绪项，请检查阶段目标或请求用户补充输入。")

        if custom_guidance:
            prompt_sections.append("")
            prompt_sections.append(f"## 5. 本轮额外指令\n{custom_guidance}")

        resumption_prompt = "\n".join(prompt_sections)

        return ProjectResumptionPackage(
            project_id=project_id,
            current_phase=phase,
            resumption_prompt=resumption_prompt,
            pending_todo_count=len(pending_todos),
            ready_todo_ids=ready_ids,
            panorama_summary=panorama_summary,
        )
