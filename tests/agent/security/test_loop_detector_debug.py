from myrm_agent_harness.agent.security.guards.loop_guard import LoopGuard


def test_debug():
    g = LoopGuard(divergence_threshold=6, warn_threshold=100, break_threshold=100)
    tools = [
        "memory_recall_tool",
        "file_read_tool",
        "bash_code_execute_tool",
        "web_search_tool",
        "browser_navigate_tool",
        "web_fetch_tool",
    ]
    for tool_name in tools:
        g.pre_check(tool_name, {"x": 1})
        print(f"Tool: {tool_name}, window: {[c.success_level for c in g._window]}")
