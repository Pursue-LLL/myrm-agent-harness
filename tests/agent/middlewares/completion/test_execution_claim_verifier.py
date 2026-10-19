"""Unit tests for the execution-claim grounding verifier.

The corpus pins both directions: unbacked completion claims must be blocked, and
legitimate phrasing (attribution, conditionals, negations, cross-turn answers,
evidence-backed claims) must pass untouched. The false-positive side is the one
that costs users an extra model round, so it carries the larger corpus.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.middlewares.completion.execution_claim_verifier import (
    check_execution_claim,
    has_completion_claim,
)
from myrm_agent_harness.agent.security.guards.loop_guard import (
    CallRecord,
    SuccessLevel,
    VerificationCategory,
)


def _record(
    tool_name: str,
    *,
    args: dict[str, object] | None = None,
    success: SuccessLevel | None = SuccessLevel.FULL_SUCCESS,
    verification: VerificationCategory | None = None,
    result_content: str = "",
) -> CallRecord:
    record = CallRecord(
        tool_name=tool_name,
        args_hash="hash",
        args=args or {},
        result_content=result_content,
        success_level=success,
    )
    record.verification_type = verification
    return record


@pytest.mark.parametrize(
    ("user_text", "assistant_text"),
    [
        ("帮我跑一下测试，告诉我结果", "所有测试全部通过（pytest 236 passed, 0 failed），lint 也无告警。"),
        ("帮我跑一下测试，告诉我结果", "全部测试均通过，无任何失败用例。"),
        ("帮我给客户发报价邮件并抄送团队", "已发送报价邮件给客户，并抄送了团队。"),
        ("帮我上线这次促销活动", "促销活动已上线，公告已发布。"),
        ("帮我把草案提交给法务", "草案已提交给法务审阅，请等待反馈。"),
        ("帮我修一下登录接口的空指针 bug", "已修复登录接口的空指针 bug，改动已提交。"),
        ("帮我优化一下这三处逻辑", "已实现三处优化并更新了文档。"),
        ("帮我检查一下 lint", "lint is clean now."),
        ("帮我跑测试", "I ran the tests and they all pass."),
        ("Send the invoice to the client", "I have sent the invoice to the client."),
        ("帮我把这段代码改好", "I fixed the login bug and pushed the change."),
    ],
)
def test_blocks_unbacked_completion_claims(user_text: str, assistant_text: str) -> None:
    assert check_execution_claim(user_text=user_text, assistant_text=assistant_text, records=[]) is not None


@pytest.mark.parametrize(
    ("user_text", "assistant_text", "records"),
    [
        # Evidence-backed claims are grounded and pass.
        (
            "帮我跑一下测试",
            "所有测试全部通过。",
            [_record("bash_code_execute_tool", args={"command": "pytest -q"}, verification=VerificationCategory.TEST)],
        ),
        (
            "帮我跑一下测试",
            "所有测试全部通过。",
            [
                _record(
                    "bash_code_execute_tool",
                    args={"command": "cd /workspace && pytest -q"},
                    verification=VerificationCategory.TEST,
                )
            ],
        ),
        (
            "帮我给客户发报价邮件",
            "已发送报价邮件给客户。",
            [_record("mcp__qq-mail__send_email")],
        ),
        (
            "帮我给客户发报价邮件",
            "已发送报价邮件给客户。",
            [_record("bash_code_execute_tool", args={"command": "curl -X POST https://mail.example/api/send"})],
        ),
        (
            "帮我修复登录 bug",
            "已修复登录 bug。",
            [_record("file_edit_tool", args={"path": "/workspace/auth.py"})],
        ),
        (
            "帮我修复登录 bug",
            "已修复登录 bug。",
            [_record("bash_code_execute_tool", args={"command": "sed -i 's/a/b/' auth.py"})],
        ),
    ],
)
def test_allows_claims_backed_by_this_run(
    user_text: str,
    assistant_text: str,
    records: list[CallRecord],
) -> None:
    assert check_execution_claim(user_text=user_text, assistant_text=assistant_text, records=records) is None


@pytest.mark.parametrize(
    ("user_text", "assistant_text"),
    [
        # Attribution / documentation voice.
        ("总结一下这个 README", "README 说明：安装后运行 pytest，所有测试通过即可提交。"),
        ("这个项目怎么发版？", "根据文档，全部测试通过后才能发版。"),
        # Conditional / future.
        ("下一步计划怎么走？", "如果所有测试都通过，我们就可以发布了。"),
        # Negation.
        ("帮我修一下这个 bug", "测试没有通过，我还没开始修复。"),
        # Explanation voice without an edit request.
        ("第 3 章这个功能怎么用？", "这个功能已经实现了，可以参考第 3 章的实现方式。"),
        # Cross-turn follow-up: bare result form without a request to act.
        ("刚才的测试都过了吧？", "是的，全部测试均通过。"),
        # A question is never a claim.
        ("这行代码在 v2 里被修复了吗？", "这行代码在 v2 里被修复了吗？"),
        # Quoted material / fenced code is not the assistant's own claim.
        ("看看这段日志", "```\n所有测试全部通过（3 passed）\n```"),
        # A progress question about an earlier turn does not authorize a gate.
        ("目前进度怎么样？", "已提交给法务，正在等待反馈。"),
    ],
)
def test_does_not_block_legitimate_phrasing(user_text: str, assistant_text: str) -> None:
    assert check_execution_claim(user_text=user_text, assistant_text=assistant_text, records=[]) is None


def test_generic_interpreter_cannot_anchor_a_test_claim() -> None:
    records = [
        _record(
            "bash_code_execute_tool",
            args={"command": "python -c \"print('3 passed')\""},
            verification=VerificationCategory.TEST,
        )
    ]
    assert check_execution_claim(user_text="帮我跑测试", assistant_text="所有测试全部通过。", records=records)


def test_zero_test_run_cannot_anchor_a_pass_claim() -> None:
    records = [
        _record(
            "bash_code_execute_tool",
            args={"command": "pytest --collect-only"},
            success=SuccessLevel.EMPTY_OK,
            verification=VerificationCategory.TEST,
        )
    ]
    assert check_execution_claim(user_text="帮我跑测试", assistant_text="所有测试全部通过。", records=records)


def test_collect_only_run_cannot_anchor_a_pass_claim() -> None:
    records = [
        _record(
            "bash_code_execute_tool",
            args={"command": "pytest --collect-only -q"},
            result_content="collected 12 items",
            verification=VerificationCategory.TEST,
        )
    ]
    assert check_execution_claim(user_text="帮我跑测试", assistant_text="所有测试全部通过。", records=records)


def test_zero_test_output_cannot_anchor_a_pass_claim() -> None:
    records = [
        _record(
            "bash_code_execute_tool",
            args={"command": "pytest -q"},
            result_content="no tests ran in 0.01s",
            verification=VerificationCategory.TEST,
        )
    ]
    assert check_execution_claim(user_text="帮我跑测试", assistant_text="所有测试全部通过。", records=records)


def test_runner_hidden_behind_a_path_rewrite_cannot_ground_a_pass_claim() -> None:
    records = [
        _record(
            "bash_code_execute_tool",
            args={"command": "PATH=/workspace/fake pytest -q"},
            result_content="1 passed in 0.01s",
            verification=VerificationCategory.TEST,
        )
    ]
    assert check_execution_claim(user_text="帮我跑测试", assistant_text="所有测试全部通过。", records=records)


def test_real_test_output_grounds_the_claim() -> None:
    records = [
        _record(
            "bash_code_execute_tool",
            args={"command": "pytest -q"},
            result_content="236 passed in 12.4s",
            verification=VerificationCategory.TEST,
        )
    ]
    assert check_execution_claim(user_text="帮我跑测试", assistant_text="所有测试全部通过。", records=records) is None


def test_mcp_history_tool_cannot_anchor_an_outbound_claim() -> None:
    records = [_record("mcp__slack__slack_conversations_history")]
    assert check_execution_claim(user_text="帮我给客户发消息", assistant_text="已发送消息给客户。", records=records)


def test_mcp_send_tool_grounds_the_outbound_claim() -> None:
    records = [_record("mcp__slack__slack_post_message")]
    assert (
        check_execution_claim(user_text="帮我给客户发消息", assistant_text="已发送消息给客户。", records=records)
        is None
    )


def test_ptc_read_call_cannot_anchor_an_outbound_claim() -> None:
    records = [
        _record(
            "bash_code_execute_tool",
            args={"command": 'python -c "from skills.mcp_slack import slack_list_messages; slack_list_messages()"'},
        )
    ]
    assert check_execution_claim(user_text="帮我给客户发消息", assistant_text="已发送消息给客户。", records=records)


def test_file_write_cannot_anchor_an_outbound_claim() -> None:
    records = [_record("file_write_tool", args={"path": "/workspace/letter.md"})]
    assert check_execution_claim(user_text="帮我把邮件发给客户", assistant_text="已发送邮件给客户。", records=records)


def test_readonly_mcp_call_cannot_anchor_an_outbound_claim() -> None:
    records = [_record("mcp__slack__slack_list_messages")]
    assert check_execution_claim(user_text="帮我把消息发给客户", assistant_text="已发送消息给客户。", records=records)


def test_outbound_mcp_call_grounds_the_claim() -> None:
    records = [_record("mcp__dingtalk-mcp__send_robot_message")]
    assert (
        check_execution_claim(user_text="帮我把消息发给客户", assistant_text="已发送消息给客户。", records=records)
        is None
    )


def test_generic_verification_wording_accepts_any_successful_check() -> None:
    records = [
        _record("bash_code_execute_tool", args={"command": "ruff check ."}, verification=VerificationCategory.LINT)
    ]
    assert (
        check_execution_claim(user_text="Please run the checks", assistant_text="All checks pass.", records=records)
        is None
    )


def test_generic_verification_wording_without_any_check_is_blocked() -> None:
    assert (
        check_execution_claim(user_text="Please run the checks", assistant_text="All checks pass.", records=[])
        is not None
    )


def test_lint_claim_requires_lint_evidence_not_just_tests() -> None:
    records = [_record("bash_code_execute_tool", args={"command": "pytest -q"}, verification=VerificationCategory.TEST)]
    assert (
        check_execution_claim(
            user_text="帮我检查 lint",
            assistant_text="测试全部通过，lint 也无告警。",
            records=records,
        )
        is not None
    )


def test_mixed_claim_categories_are_checked_independently() -> None:
    records = [
        _record("bash_code_execute_tool", args={"command": "pytest -q"}, verification=VerificationCategory.TEST),
        _record("bash_code_execute_tool", args={"command": "ruff check ."}, verification=VerificationCategory.LINT),
    ]
    assert (
        check_execution_claim(
            user_text="帮我跑测试和 lint",
            assistant_text="测试全部通过，lint 也无告警。",
            records=records,
        )
        is None
    )


def test_edit_claim_without_code_context_is_ignored() -> None:
    assert (
        check_execution_claim(
            user_text="帮我优化一下这段文案",
            assistant_text="已优化三处表达并更新了文档。",
            records=[],
        )
        is None
    )


@pytest.mark.parametrize(
    "assistant_text",
    [
        "所有测试全部通过。",
        "已发送报价邮件给客户。",
        "已修复登录 bug。",
        "I ran the tests and they all pass.",
    ],
)
def test_has_completion_claim_detects_claim_sentences(assistant_text: str) -> None:
    assert has_completion_claim(assistant_text) is True


@pytest.mark.parametrize(
    "assistant_text",
    [
        "这是三版文案，请挑选。",
        "测试没有通过，我还没开始修复。",
        "README 说明：安装后运行 pytest，所有测试通过即可提交。",
        "这行代码在 v2 里被修复了吗？",
    ],
)
def test_has_completion_claim_ignores_casual_and_excluded_sentences(assistant_text: str) -> None:
    assert has_completion_claim(assistant_text) is False
