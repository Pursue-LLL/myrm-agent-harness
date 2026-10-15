import re

from myrm_agent_harness.agent.sub_agents.graph_triage.types import (
    GraphTriageDecision,
    TaskComplexityCategory,
    TriageFeatureVector,
    TriageVerdict,
)

_EXPLORATORY_KEYWORDS: set[str] = {
    "brainstorm",
    "brainstorming",
    "discuss",
    "opinion",
    "what do you think",
    "thoughts on",
    "头脑风暴",
    "聊聊",
    "你觉得",
    "讨论一下",
    "有什么建议",
    "随便聊聊",
}

_SIMPLE_SINGLE_STEP_PATTERNS: list[str] = [
    r"^(fix|correct)\s+(a\s+)?(typo|spelling|grammar)",
    r"^(改一下|修改|修复)?(错别字|拼写|标点)",
    r"^(lookup|query|check)\s+(single|the)\s+(status|version|price)",
    r"^(查一下|查询|查看)?(状态|版本|配置|当前时间)",
    r"^(explain|what is)\s+[a-zA-Z0-9_\-\.]{1,30}$",
    r"^(解释|说明)\s*[\u4e00-\u9fa5a-zA-Z0-9_\-\.]{1,20}$",
]


class GraphApplicabilityTriageGate:
    """Evaluates task applicability for graph-based multi-agent orchestration.

    Intercepts unnecessary fan-out on trivial, conversational, or strictly
    linear tasks to prevent excessive latency and token waste.
    """

    def extract_features(
        self,
        prompt: str,
        subtasks: list[dict[str, list[str]]] | None = None,
    ) -> TriageFeatureVector:
        cleaned_prompt = prompt.strip()
        prompt_len = len(cleaned_prompt)
        lower_prompt = cleaned_prompt.lower()

        is_exploratory = any(kw in lower_prompt for kw in _EXPLORATORY_KEYWORDS)

        declared_count = 0
        independent_count = 0
        max_depth = 0
        has_heavyweight = False

        if subtasks:
            declared_count = len(subtasks)
            # subtasks is expected as list of dicts: {"id": "...", "deps": [...], "heavy": bool}
            task_ids: set[str] = {st.get("id", str(i)) for i, st in enumerate(subtasks)}
            deps_map: dict[str, list[str]] = {
                st.get("id", str(i)): st.get("deps", []) for i, st in enumerate(subtasks)
            }
            heavy_flags = [bool(st.get("heavy", False)) for st in subtasks]
            has_heavyweight = any(heavy_flags) or declared_count >= 2

            independent_tasks = [tid for tid, deps in deps_map.items() if not deps]
            independent_count = len(independent_tasks)

            # Compute depth
            depths: dict[str, int] = {}

            def get_depth(tid: str, visited: set[str]) -> int:
                if tid in depths:
                    return depths[tid]
                if tid in visited:
                    return 1
                visited.add(tid)
                cur_deps = deps_map.get(tid, [])
                if not cur_deps:
                    depths[tid] = 1
                    return 1
                max_d = max([get_depth(d, visited.copy()) for d in cur_deps if d in task_ids], default=0) + 1
                depths[tid] = max_d
                return max_d

            for tid in task_ids:
                d = get_depth(tid, set())
                if d > max_depth:
                    max_depth = d
        else:
            # Fallback heuristic if subtasks not explicitly parsed
            if prompt_len > 300 or "parallel" in lower_prompt or "同时" in cleaned_prompt:
                declared_count = 2
                independent_count = 2
                max_depth = 1
                has_heavyweight = True
            elif prompt_len > 100:
                declared_count = 1
                independent_count = 1
                max_depth = 1

        return TriageFeatureVector(
            prompt_length=prompt_len,
            declared_subtasks_count=declared_count,
            independent_parallel_count=independent_count,
            max_dependency_depth=max_depth,
            is_conversational_inquiry=is_exploratory,
            has_isolated_heavyweight_steps=has_heavyweight,
        )

    def evaluate(
        self,
        prompt: str,
        subtasks: list[dict[str, list[str]]] | None = None,
    ) -> GraphTriageDecision:
        features = self.extract_features(prompt, subtasks)
        lower_prompt = prompt.strip().lower()

        # Rule 1: Simple single step match
        is_simple_step = any(
            re.search(pat, lower_prompt) for pat in _SIMPLE_SINGLE_STEP_PATTERNS
        ) or (features.prompt_length < 40 and features.declared_subtasks_count <= 1 and not features.is_conversational_inquiry)

        if is_simple_step:
            return GraphTriageDecision(
                verdict=TriageVerdict.REJECT_TO_SINGLE_AGENT,
                category=TaskComplexityCategory.SIMPLE_SINGLE_STEP,
                reason="任务属于单一单步操作（如错别字修复或单点查询），图多智能体编排会导致严重响应延迟与数十倍 Token 浪费，强制降级为单 Agent 执行。",
                recommended_mode="Single-Agent Direct Execution",
                estimated_speedup_ratio=5.0,
                estimated_tokens_saved=45_000,
                features=features,
            )

        # Rule 2: Open-ended exploratory conversation
        if features.is_conversational_inquiry and features.independent_parallel_count < 2:
            return GraphTriageDecision(
                verdict=TriageVerdict.REJECT_TO_CONVERSATIONAL,
                category=TaskComplexityCategory.EXPLORATORY_CHAT,
                reason="任务属于未定型探索性头脑风暴或人机互动对话，盲目拉起图编排会破坏交互上下文连贯性，保持单 Agent 交互模式。",
                recommended_mode="Conversational Interactive Session",
                estimated_speedup_ratio=3.5,
                estimated_tokens_saved=30_000,
                features=features,
            )

        # Rule 3: Strictly sequential pipeline
        if (
            features.declared_subtasks_count >= 2
            and features.independent_parallel_count <= 1
            and features.max_dependency_depth == features.declared_subtasks_count
        ):
            return GraphTriageDecision(
                verdict=TriageVerdict.REJECT_TO_LINEAR_PIPELINE,
                category=TaskComplexityCategory.STRICTLY_SEQUENTIAL,
                reason="所有子任务具备强因果时序依赖链条，不存在独立可并行扇出分支，图编排只会引入拓扑空转开销，保持轻量线性流水线模式。",
                recommended_mode="Linear Sequential Pipeline",
                estimated_speedup_ratio=2.0,
                estimated_tokens_saved=20_000,
                features=features,
            )

        # Rule 4: Parallel Heavyweight admittance
        if features.independent_parallel_count >= 2:
            return GraphTriageDecision(
                verdict=TriageVerdict.ADMIT_GRAPH,
                category=TaskComplexityCategory.PARALLEL_HEAVYWEIGHT,
                reason="检测到多个独立可并行的重型子任务，符合图编排准入条件，准许激活多智能体图并发编排。",
                recommended_mode="Parallel Multi-Agent Graph Engine",
                estimated_speedup_ratio=3.2,
                estimated_tokens_saved=0,
                features=features,
            )

        # Default fallback: single agent execution for unclassified small tasks
        return GraphTriageDecision(
            verdict=TriageVerdict.REJECT_TO_SINGLE_AGENT,
            category=TaskComplexityCategory.SIMPLE_SINGLE_STEP,
            reason="任务规模较小且未表现出高并发需求，降级为单 Agent 模式以保证敏捷响应。",
            recommended_mode="Single-Agent Direct Execution",
            estimated_speedup_ratio=2.5,
            estimated_tokens_saved=15_000,
            features=features,
        )
