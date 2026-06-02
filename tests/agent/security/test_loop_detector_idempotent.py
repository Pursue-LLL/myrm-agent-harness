from myrm_agent_harness.agent.security.guards.loop_guard import LoopAction, LoopGuard


def test_idempotent_tool_relaxed_threshold():
    g = LoopGuard(warn_threshold=3, break_threshold=5)

    # file_read_tool is idempotent, so threshold is 6
    for _ in range(5):
        v = g.pre_check("file_read_tool", {"path": "test.txt"})
        assert v.action == LoopAction.ALLOW

    v = g.pre_check("file_read_tool", {"path": "test.txt"})
    assert v.action == LoopAction.WARN

def test_bash_ls_is_idempotent():
    g = LoopGuard(warn_threshold=3, break_threshold=5)

    # bash_tool with 'ls' is idempotent, so threshold is 6
    for _ in range(5):
        v = g.pre_check("bash_tool", {"command": "ls -la /tmp"})
        assert v.action == LoopAction.ALLOW

    v = g.pre_check("bash_tool", {"command": "ls -la /tmp"})
    assert v.action == LoopAction.WARN

def test_bash_rm_is_not_idempotent():
    g = LoopGuard(warn_threshold=3, break_threshold=5)

    # bash_tool with 'rm' is NOT idempotent, so threshold is 3
    for _ in range(2):
        v = g.pre_check("bash_tool", {"command": "rm -rf /tmp/test"})
        assert v.action == LoopAction.ALLOW

    v = g.pre_check("bash_tool", {"command": "rm -rf /tmp/test"})
    assert v.action == LoopAction.WARN
