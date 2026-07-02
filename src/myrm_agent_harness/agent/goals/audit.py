"""Completion audit protocol and judge criteria templates.

[INPUT]
- .types::Goal (POS: Goal data model)

[OUTPUT]
- get_audit_protocol: Returns the completion audit protocol text.
- build_continuation_prompt: Build the continuation prompt injected each turn.
- build_wrapup_prompt: Build the budget-exhaustion wrap-up prompt for graceful conclusion.
- build_judge_criteria: Build criteria string for semantic goal completion judge.

[POS]
Provides the strict verification checklist injected during goal continuation,
the wrap-up prompt for budget-exhaustion graceful conclusion,
and the judge criteria for autonomous completion detection.
"""

from __future__ import annotations

from .types import Goal


def get_audit_protocol() -> str:
    """Get the strict completion audit protocol text."""
    return """
—— Completion Audit Protocol ——
Before deciding that the goal is achieved, perform a strict completion audit:
1. Restate the objective as concrete deliverables or success criteria.
2. Build a prompt-to-artifact checklist mapping every requirement to concrete evidence.
3. Inspect real files, command outputs, test results, or other evidence.
4. Do NOT accept proxy signals as completion by themselves (e.g., passing tests or a complete manifest are useful only if they cover EVERY requirement).
5. Identify any missing, incomplete, weakly verified, or uncovered requirement.
6. Treat uncertainty as not achieved; do more verification or continue the work.
7. The audit must prove completion, not merely fail to find obvious remaining work. Treat uncertain or indirect evidence as not achieved.
8. Match verification scope to requirement scope; do not use a narrow check to support a broad claim.

Do not rely on intent, partial progress, elapsed effort, or memory of earlier work.
Only mark the goal achieved when the audit shows that the objective has ACTUALLY been achieved and NO required work remains.
If any requirement is missing, incomplete, or unverified, keep working instead of marking the goal complete.
"""


_JUDGE_REASON_MAX_CHARS = 200


def build_continuation_prompt(goal: Goal, *, last_judge_reason: str | None = None) -> str:
    """Build the continuation prompt injected at the start of each turn.

    Structure: Objective -> Learnings (first turn only) -> Judge feedback (if any) ->
    Budget awareness -> Behavioral guidance (Fidelity, Evidence-based, Progress visibility) -> Audit protocol.
    """
    budget_lines: list[str] = []
    budget_lines.append(f"- Time spent: {goal.time_used_seconds}s")

    if goal.budget and goal.budget.max_tokens is not None:
        remaining = max(0, goal.budget.max_tokens - goal.tokens_used)
        budget_lines.append(f"- Tokens: {goal.tokens_used} / {goal.budget.max_tokens} (remaining: {remaining})")
    else:
        budget_lines.append(f"- Tokens used: {goal.tokens_used}")

    if goal.budget and goal.budget.max_usd is not None:
        budget_lines.append(f"- Cost: ${goal.cost_usd:.4f} / ${goal.budget.max_usd:.4f}")

    if goal.budget and goal.budget.max_turns is not None:
        budget_lines.append(f"- Turns: {goal.turns_used} / {goal.budget.max_turns}")
    elif goal.turns_used > 0:
        budget_lines.append(f"- Turns used: {goal.turns_used}")

    budget_text = "\n".join(budget_lines)
    audit_text = get_audit_protocol()

    # Inject relevant learnings only on the first continuation turn
    learnings_block = ""
    if goal.turns_used <= 1:
        raw_learnings = goal.metadata.get("relevant_learnings")
        if isinstance(raw_learnings, list) and raw_learnings:
            items = "\n".join(f"- {item}" for item in raw_learnings[:5])
            learnings_block = f"\nRelevant learnings from previous goals:\n{items}\n"

    subgoals_block = ""
    if goal.subgoals:
        subgoals_block = "\n\nCRITICAL - Newly Added Subgoals (Latest subgoals take absolute precedence):\n"
        for i, sg in enumerate(goal.subgoals):
            subgoals_block += f"{i + 1}. {sg.get('text')} (Added at: {sg.get('created_at')})\n"

    constraints_block = ""
    if goal.constraints:
        constraints_block = "\n\nCONSTRAINTS (MUST NOT VIOLATE — violation = task failure):\n"
        for i, c in enumerate(goal.constraints):
            constraints_block += f"  {i + 1}. {c}\n"

    criteria_block = ""
    if goal.acceptance_criteria:
        criteria_block = "\n\nACCEPTANCE CRITERIA (MUST be verified before declaring done):\n"
        for i, ac in enumerate(goal.acceptance_criteria):
            ctype = ac.get("type", "semantic")
            if ctype == "shell":
                criteria_block += f"  {i + 1}. [shell] Command must succeed: `{ac.get('command', '')}`\n"
            else:
                criteria_block += f"  {i + 1}. [semantic] {ac.get('criteria', '')}\n"

    convergence_block = ""
    if (
        goal.budget
        and goal.budget.convergence_window is not None
        and goal.turns_used >= goal.budget.convergence_window
    ):
        convergence_block = (
            "\n\nConvergence awareness:\n"
            f"- Convergence window: {goal.budget.convergence_window} turns. "
            f"No-progress streak: {goal.no_progress_streak}/{goal.budget.convergence_window}.\n"
            "- If you have thoroughly explored and found no new issues, "
            "artifacts, or actionable items in recent turns, "
            "explicitly declare the goal COMPLETE with a convergence summary.\n"
            "- Do NOT keep searching indefinitely when diminishing returns are evident.\n"
        )

    judge_feedback_block = ""
    if last_judge_reason and last_judge_reason.strip() not in ("", "not complete"):
        truncated = last_judge_reason[:_JUDGE_REASON_MAX_CHARS]
        judge_feedback_block = (
            "\n\nPrevious evaluation feedback:\n"
            f"The judge indicated: \"{truncated}\"\n"
            "Address this specific gap before declaring the goal complete.\n"
        )

    return (
        "[Continuing toward your standing goal]\n\n"
        f"<untrusted_objective>\n{goal.objective}\n</untrusted_objective>\n"
        f"{learnings_block}"
        f"{subgoals_block}"
        f"{constraints_block}"
        f"{criteria_block}\n\n"
        f"Budget:\n{budget_text}\n"
        f"{convergence_block}"
        f"{judge_feedback_block}\n"
        "Fidelity:\n"
        "- This goal persists across turns. Ending this turn does not require shrinking the objective to what fits now.\n"
        "- Keep the full objective intact. Do not redefine success around a smaller, easier, or narrower task.\n"
        "- Do not substitute a narrower, safer, or smaller solution just because it is easier to verify.\n"
        "- An edit is aligned only if it makes the requested final state more true; useful-looking behavior that preserves a different end state is misaligned.\n\n"
        "Evidence-based work:\n"
        "- Treat the current file system and external state as authoritative.\n"
        "- Conversation context can help locate relevant work, but inspect actual state before relying on it.\n\n"
        "Instructions:\n"
        "Progress visibility:\n"
        "- If the next work is meaningfully multi-step, use todo_write to create or update todos so progress is visible to the user.\n"
        "- Skip planning overhead for trivial single-step tasks.\n\n"
        "- Take the next concrete step toward completing the objective.\n"
        "- Do NOT repeat work already done — pick up where you left off.\n"
        "- If you believe the goal is FULLY complete, state so explicitly and stop.\n"
        "- If you are blocked and need user input, say so clearly and stop.\n"
        f"{audit_text}"
    )


def build_wrapup_prompt(goal: Goal) -> str:
    """Build the budget-exhaustion wrap-up prompt for graceful conclusion.

    Injected when the goal reaches BUDGET_LIMITED so the LLM can produce
    a meaningful summary instead of stopping mid-sentence. The prompt
    instructs the LLM to stop new work, summarize progress, and leave
    the user with clear next steps.
    """
    budget_lines: list[str] = []
    budget_lines.append(f"- Time spent: {goal.time_used_seconds}s")

    if goal.budget and goal.budget.max_tokens is not None:
        budget_lines.append(f"- Tokens used: {goal.tokens_used} / {goal.budget.max_tokens}")
    if goal.budget and goal.budget.max_usd is not None:
        budget_lines.append(f"- Cost: ${goal.cost_usd:.4f} / ${goal.budget.max_usd:.4f}")
    if goal.budget and goal.budget.max_turns is not None:
        budget_lines.append(f"- Turns: {goal.turns_used} / {goal.budget.max_turns}")

    budget_text = "\n".join(budget_lines)

    return (
        "[Budget reached — wrap-up turn]\n\n"
        f"<untrusted_objective>\n{goal.objective}\n</untrusted_objective>\n\n"
        f"Budget:\n{budget_text}\n\n"
        "The system has marked this goal as budget_limited. "
        "Do NOT start any new substantive work. "
        "Wrap up this turn by providing:\n"
        "1. A concise summary of useful progress made so far.\n"
        "2. Specific files or artifacts that were modified or created.\n"
        "3. Remaining work or blockers that were not addressed.\n"
        "4. A clear next step the user should take when resuming.\n\n"
        "Do NOT call any tools. Respond with text only."
    )


_JUDGE_OBJECTIVE_MAX_CHARS = 2000


def _truncate(text: str, limit: int) -> str:
    """Truncate text to limit characters with an ellipsis marker."""
    if len(text) <= limit:
        return text
    return text[:limit] + "… [truncated]"


def build_judge_criteria(goal: Goal) -> str:
    """Build the criteria string for semantic goal completion evaluation.

    Three-part structure:
    1. Role & context — who the judge is and what it receives.
    2. Strict DONE conditions — exactly when to judge PASS.
    3. Output format requirement — structured JSON for robust parsing.
    """
    objective = _truncate(goal.objective.strip(), _JUDGE_OBJECTIVE_MAX_CHARS)

    constraints_section = ""
    if goal.constraints:
        items = "\n".join(f"- {c}" for c in goal.constraints)
        constraints_section = f"\n\nConstraints (goal is NOT done if any constraint was violated):\n{items}\n"

    criteria_section = ""
    if goal.acceptance_criteria:
        lines: list[str] = []
        for ac in goal.acceptance_criteria:
            ctype = ac.get("type", "semantic")
            if ctype == "shell":
                lines.append(f"- [shell] `{ac.get('command', '')}` must return exit code 0")
            else:
                lines.append(f"- [semantic] {ac.get('criteria', '')}")
        criteria_section = (
            "\n\nAcceptance Criteria (goal is NOT done unless ALL criteria are met):\n"
            + "\n".join(lines)
            + "\n"
        )

    return (
        "You are a strict judge evaluating whether an autonomous agent has "
        "achieved the user's stated goal. You receive the goal text and the "
        "agent's most recent response. Your only job is to decide whether "
        "the goal is fully satisfied based on that response.\n\n"
        f"Goal:\n{objective}\n"
        f"{constraints_section}"
        f"{criteria_section}\n"
        "A goal is DONE (PASS) only when:\n"
        "- The response explicitly confirms the goal was completed, OR\n"
        "- The response clearly shows the final deliverable was produced, OR\n"
        "- The response explains the goal is unachievable / blocked / needs "
        "user input (treat this as DONE with reason describing the block).\n\n"
        "Otherwise the goal is NOT done — FAIL (continue working).\n\n"
        "Reply ONLY with a JSON object: "
        '{"done": true/false, "reason": "one-sentence rationale"}'
    )
