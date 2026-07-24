from myrm_agent_harness.agent.meta_tools.answer_user_tool import ANSWER_USER_TOOL_DESCRIPTION


def test_answer_user_tool_description_is_compact() -> None:
    assert len(ANSWER_USER_TOOL_DESCRIPTION) <= 1024
    assert "request_answer_user_tool" not in ANSWER_USER_TOOL_DESCRIPTION.lower()
