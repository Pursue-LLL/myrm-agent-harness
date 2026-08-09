"""Repro: does the hygiene + dangling repair chain keep request payloads well-formed?

Simulates the CompletionGuard aafter_model behavior (mutate last AI msg in place,
append the same reference) then runs sanitize_tool_history + repair_dangling_tool_calls
the way the middleware chain would, and checks whether the final payload still has
a dangling tool_call (the LiteLLM "tool_calls must be followed by tool messages" 400).
"""

import sys

sys.path.insert(0, "src")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.middlewares.dangling_tool_call_middleware import (
    repair_dangling_tool_calls,
)
from myrm_agent_harness.agent.middlewares.tool_history_hygiene import (
    sanitize_tool_history,
)


def payload_is_well_formed(messages: list) -> bool:
    """Mimic the OpenAI/LiteLLM contract: every AI tool_call must be followed by a matching ToolMessage."""
    pending: dict[str, str] = {}
    for m in messages:
        if m.type == "ai":
            for tc in m.tool_calls or []:
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                if tc_id:
                    pending[tc_id] = tc.get("name") or tc.get("id") or "?"
        elif m.type == "tool":
            pending.pop(m.tool_call_id, None)
    return not pending


def dump(messages: list, label: str) -> None:
    print(f"\n--- {label} ---")
    for m in messages:
        extra = ""
        if m.type == "ai":
            tcs = [tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None) for tc in (m.tool_calls or [])]
            extra = f" tool_calls={tcs} content={(str(m.content)[:40])!r}"
        elif m.type == "tool":
            extra = f" tool_call_id={m.tool_call_id}"
        print(f"  {m.type}: {extra}")


def check(name: str, messages: list) -> None:
    sanitized = sanitize_tool_history(messages)
    repaired = repair_dangling_tool_calls(sanitized)
    ok = payload_is_well_formed(repaired)
    print(f"[{name}] payload well-formed: {ok}")
    if not ok:
        dump(repaired, f"{name} repaired payload")


def main() -> None:
    # ---- Scenario 1: one completion attempt intercepted by CompletionGuard ----
    # Model outputs a plain completion AI message (no tool_calls).
    ai = AIMessage(content="Task complete.", tool_calls=[])
    msgs = [HumanMessage(content="run it"), ai]
    # CompletionGuard mutates the SAME reference and appends it.
    ai.tool_calls = [
        {"name": "_completion_check", "args": {"workspace_root": ""},
         "id": "call_aaaa1111", "type": "tool_call"}
    ]
    msgs.append(ai)  # same object appended again
    msgs.append(ToolMessage(content="checklist ok", tool_call_id="call_aaaa1111"))
    check("S1 guard-inject once", msgs)

    # ---- Scenario 2: two interception rounds accumulate ----
    msgs2: list = [HumanMessage(content="run it")]
    for i, (mid, rid) in enumerate(
        [("call_aaaa2222", "res_aaaa2222"), ("call_bbbb3333", "res_bbbb3333")]
    ):
        ai2 = AIMessage(content=f"round {i} done", tool_calls=[])
        msgs2.append(ai2)
        ai2.tool_calls = [
            {"name": "_completion_check", "args": {"workspace_root": ""},
             "id": mid, "type": "tool_call"}
        ]
        msgs2.append(ai2)
        msgs2.append(ToolMessage(content="blocked", tool_call_id=mid))
    check("S2 two rounds", msgs2)

    # ---- Scenario 3: real tool call then interception ----
    msgs3: list = [HumanMessage(content="write file")]
    ai_tool = AIMessage(
        content="", tool_calls=[
            {"name": "write_file", "args": {"path": "a.txt"}, "id": "call_tool0001", "type": "tool_call"}
        ]
    )
    msgs3.append(ai_tool)
    msgs3.append(ToolMessage(content="written", tool_call_id="call_tool0001"))
    ai_finish = AIMessage(content="Done writing.", tool_calls=[])
    msgs3.append(ai_finish)
    # Guard replaces tool_calls on the SAME reference (was empty) and appends.
    ai_finish.tool_calls = [
        {"name": "_completion_check", "args": {"workspace_root": ""},
         "id": "call_cccc4444", "type": "tool_call"}
    ]
    msgs3.append(ai_finish)
    msgs3.append(ToolMessage(content="blocked", tool_call_id="call_cccc4444"))
    check("S3 tool + intercept", msgs3)

    # ---- Scenario 4: Mixed Message Guard strips tool_calls (same ref) ----
    msgs4: list = [HumanMessage(content="q")]
    ai4 = AIMessage(
        content="A long substantive final answer " * 40,  # > 500 chars, structured
        tool_calls=[
            {"name": "web_search_tool", "args": {"q": "x"}, "id": "call_strip9999", "type": "tool_call"}
        ],
    )
    msgs4.append(ai4)
    ai4.tool_calls = []  # Mixed Message Guard mutates same reference
    msgs4.append(ai4)
    check("S4 mixed message strip", msgs4)

    # ---- Scenario 5: full realistic accumulation (3 guard rounds) ----
    msgs5: list = [HumanMessage(content="do the task")]
    for i in range(3):
        a = AIMessage(content=f"attempt {i}", tool_calls=[])
        msgs5.append(a)
        mid = f"call_guard00{i}"
        a.tool_calls = [
            {"name": "_completion_check", "args": {"workspace_root": ""},
             "id": mid, "type": "tool_call"}
        ]
        msgs5.append(a)
        msgs5.append(ToolMessage(content="blocked", tool_call_id=mid))
    check("S5 three guard rounds", msgs5)


if __name__ == "__main__":
    main()
