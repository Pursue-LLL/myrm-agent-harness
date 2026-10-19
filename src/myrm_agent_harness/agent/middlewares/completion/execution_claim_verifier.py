"""Execution-claim grounding verifier for CompletionGuard.

Detects load-bearing completion claims in the assistant's final response whose
evidence is missing from the run's own tool-call record. A claim is grounded
only by evidence produced **in this run** — a self-report is never evidence.

Three claim families (each grounded by a different evidence predicate):
1. **Verification results** — "all tests pass", "lint is clean", "build
   succeeded". Tests additionally require a *real test runner* (a generic
   interpreter run such as ``python -c "print('3 passed')"`` cannot anchor a
   test claim) and a non-trivial outcome (``EMPTY_OK`` — zero collected tests —
   never grounds a pass claim).
2. **Outbound / irreversible actions** — "sent", "published", "deployed",
   "submitted", "committed". Grounded by a successful MCP call (direct or PTC
   bash) that is not a read-only call, a successful outbound command (curl,
   mail, git push, docker push, ...), or a tool whose name carries outbound
   semantics. Plain file writes, read-only MCP calls and browser navigation
   never ground an outbound claim: they did not deliver anything to a third
   party.
3. **Code modification** — "fixed", "implemented", "refactored". Only checked
   when the user asked for a code change in this turn; grounded by a successful
   workspace write or a successful shell mutation.

Trigger discipline (false positives are the main risk):
- sentence-level scan; fenced code blocks and inline code are ignored;
- sentences carrying attribution ("README says ..."), conditionals ("if ..."),
  negations ("not fixed") never trigger;
- first-person completion forms ("I ran ...", "我已发送") trigger on their own;
  bare result forms ("all tests pass") require the matching request intent in
  the latest user message, so cross-turn follow-ups ("did the tests pass?")
  stay silent.

Boundary (stated, not hidden): evidence proves an action ran; it does not prove
the claim is semantically correct, and a runner that lies about its own results
is out of scope.

[INPUT]
- agent.security.guards.loop_guard::CallRecord, SuccessLevel, ToolGroup, VerificationCategory, get_tool_group (POS: 工具调用记录与成功等级 SSOT)
- toolkits.mcp.config::is_mcp_tool_name (POS: Direct FC MCP 工具名识别)

[OUTPUT]
- check_execution_claim(): 三类承重断言与本轮执行轨迹不一致时的阻断原因，或 None
- has_completion_claim(): 回答里是否出现完成式断言（供披露策略判定 PLAN 档是否值得展示）

[POS]
CompletionGuard 的断言接地判定器。把最终汇报里的完成式断言绑定到本轮真实工具记录，不满足即要求取证或如实改写。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.security.guards.loop_guard import (
    SuccessLevel,
    ToolGroup,
    VerificationCategory,
    get_tool_group,
)
from myrm_agent_harness.toolkits.mcp.config import is_mcp_tool_name

if TYPE_CHECKING:
    from myrm_agent_harness.agent.security.guards.loop_guard import CallRecord

from myrm_agent_harness.agent.middlewares.completion.execution_claim_lexicon import (
    _ACTION_INTENT,
    _ATTRIBUTION,
    _BASH_MUTATION,
    _CATEGORY_KEYWORDS,
    _CODE_CONTEXT,
    _COMMAND_SEPARATOR,
    _CONDITIONAL,
    _EDIT_CLAIM_EN,
    _EDIT_CLAIM_ZH,
    _EDIT_INTENT,
    _ENV_ASSIGNMENT_PREFIX,
    _EXPLANATION_CONTEXT,
    _FENCED_BLOCK,
    _INLINE_CODE,
    _MCP_PTC_BASH_MARKER,
    _NEGATED,
    _OUTBOUND_BARE_RESULT,
    _OUTBOUND_COMMAND,
    _OUTBOUND_FIRST_PERSON,
    _OUTBOUND_TOOL_NAME,
    _READONLY_MCP_TOOL,
    _SENTENCE_SPLIT,
    _STRICT_TEST_RUNNER,
    _TEST_DRY_RUN,
    _TEST_PATH_REWRITE,
    _TEST_ZERO_SHAPE,
    _VERIFICATION_FIRST_PERSON,
    _VERIFICATION_INTENT,
    _VERIFICATION_RESULT_EN,
    _VERIFICATION_RESULT_ZH,
)


def _command_text(record: CallRecord) -> str:
    args = getattr(record, "args", None)
    if not isinstance(args, dict):
        return ""
    command = args.get("command")
    return command if isinstance(command, str) else ""


def _succeeded(record: CallRecord) -> bool:
    """True when a tool record proves the call actually executed successfully."""
    success_level = getattr(record, "success_level", None)
    return success_level is not None and success_level not in (SuccessLevel.FAILURE, SuccessLevel.EMPTY_OK)


def _is_strict_test_runner(command: str) -> bool:
    for raw_segment in _COMMAND_SEPARATOR.split(command):
        segment = _ENV_ASSIGNMENT_PREFIX.sub("", raw_segment.strip())
        if segment and _STRICT_TEST_RUNNER.match(segment):
            return True
    return False


def _mentioned_categories(sentence: str) -> list[VerificationCategory]:
    """Categories the claim names. Empty means the wording is generic
    ("all checks pass"), which is grounded by any successful verification."""
    lowered = sentence.lower()
    categories: list[VerificationCategory] = []
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword.lower() in lowered for keyword in keywords):
            categories.append(category)
    return categories


def _is_test_pass_evidence(record: CallRecord) -> bool:
    """A test claim is grounded by a real runner with a non-empty run behind it."""
    command = _command_text(record)
    if not _is_strict_test_runner(command) or _TEST_DRY_RUN.search(command) or _TEST_PATH_REWRITE.search(command):
        return False
    return not _TEST_ZERO_SHAPE.search(str(getattr(record, "result_content", "")))


def _category_evidence(records: Sequence[CallRecord], category: VerificationCategory) -> bool:
    for record in records:
        if getattr(record, "verification_type", None) != category or not _succeeded(record):
            continue
        if category is VerificationCategory.TEST and not _is_test_pass_evidence(record):
            continue
        return True
    return False


def _any_verification_evidence(records: Sequence[CallRecord]) -> bool:
    for record in records:
        category = getattr(record, "verification_type", None)
        if category is None or not _succeeded(record):
            continue
        if category is VerificationCategory.TEST and not _is_test_pass_evidence(record):
            continue
        return True
    return False


def _outbound_mcp_evidence(tool_name: str) -> bool:
    """An MCP call grounds an outbound claim only with outbound semantics."""
    tool_part = tool_name.rsplit("__", 1)[-1]
    return bool(_OUTBOUND_TOOL_NAME.search(tool_part)) and not _READONLY_MCP_TOOL.search(tool_part)


def _outbound_evidence(records: Sequence[CallRecord]) -> bool:
    for record in records:
        if not _succeeded(record):
            continue
        tool_name = str(getattr(record, "tool_name", ""))
        if is_mcp_tool_name(tool_name):
            if _outbound_mcp_evidence(tool_name):
                return True
            continue
        if tool_name == "bash_code_execute_tool":
            command = _command_text(record)
            if _MCP_PTC_BASH_MARKER in command:
                if _OUTBOUND_TOOL_NAME.search(command) and not _READONLY_MCP_TOOL.search(command):
                    return True
                continue
            if _OUTBOUND_COMMAND.search(command):
                return True
            continue
        if _OUTBOUND_TOOL_NAME.search(tool_name):
            return True
    return False


def _edit_evidence(records: Sequence[CallRecord]) -> bool:
    for record in records:
        if not _succeeded(record):
            continue
        if get_tool_group(str(getattr(record, "tool_name", ""))) == ToolGroup.WRITE:
            return True
        if str(getattr(record, "tool_name", "")) == "bash_code_execute_tool" and _BASH_MUTATION.search(
            _command_text(record)
        ):
            return True
    return False


def _sentences(text: str) -> list[str]:
    stripped = _FENCED_BLOCK.sub(" ", text)
    stripped = _INLINE_CODE.sub(" ", stripped)
    return [sentence.strip() for sentence in _SENTENCE_SPLIT.split(stripped) if sentence.strip()]


def _excluded(sentence: str) -> bool:
    return bool(
        _ATTRIBUTION.search(sentence)
        or _CONDITIONAL.search(sentence)
        or _NEGATED.search(sentence)
        or _EXPLANATION_CONTEXT.search(sentence)
    )


def _excerpt(sentence: str, limit: int = 140) -> str:
    compact = " ".join(sentence.split())
    return compact if len(compact) <= limit else f"{compact[:limit]}..."


def _verification_reason(
    sentence: str,
    records: Sequence[CallRecord],
    *,
    first_person: bool,
    user_text: str | None,
) -> str | None:
    if not first_person and not (user_text and _VERIFICATION_INTENT.search(user_text)):
        return None
    categories = _mentioned_categories(sentence)
    if categories:
        missing = [category.value for category in categories if not _category_evidence(records, category)]
    else:
        missing = [] if _any_verification_evidence(records) else ["verification"]
    if not missing:
        return None
    return (
        "verification claim without executed evidence: "
        f"'{_excerpt(sentence)}' (no successful {', '.join(missing)} run recorded in this turn). "
        "Run the check now, or rewrite the claim to state exactly what was verified and what was not."
    )


def _outbound_reason(
    sentence: str,
    records: Sequence[CallRecord],
    *,
    first_person: bool,
    user_text: str | None,
) -> str | None:
    if not first_person and not (user_text and _ACTION_INTENT.search(user_text)):
        return None
    if _outbound_evidence(records):
        return None
    return (
        "outbound action claim without executed evidence: "
        f"'{_excerpt(sentence)}' (no successful outbound tool call recorded in this turn). "
        "Perform the action now, or rewrite the claim to state that it was not performed."
    )


def _edit_reason(
    sentence: str,
    records: Sequence[CallRecord],
    *,
    user_text: str | None,
) -> str | None:
    if not user_text or not _EDIT_INTENT.search(user_text) or not _CODE_CONTEXT.search(user_text):
        return None
    if _edit_evidence(records):
        return None
    return (
        "code change claim without executed evidence: "
        f"'{_excerpt(sentence)}' (no successful workspace write recorded in this turn). "
        "Make the change now, or rewrite the claim to state what was actually changed."
    )


def check_execution_claim(
    *,
    user_text: str | None,
    assistant_text: str,
    records: Sequence[CallRecord],
) -> str | None:
    """Return a block reason when the final response claims work the trace cannot support."""
    if not assistant_text.strip():
        return None

    for sentence in _sentences(assistant_text):
        if sentence.endswith(("?", "？")) or _excluded(sentence):
            continue

        first_person = bool(_VERIFICATION_FIRST_PERSON.search(sentence))
        if first_person or _VERIFICATION_RESULT_ZH.search(sentence) or _VERIFICATION_RESULT_EN.search(sentence):
            reason = _verification_reason(sentence, records, first_person=first_person, user_text=user_text)
            if reason is not None:
                return reason

        outbound_first_person = bool(_OUTBOUND_FIRST_PERSON.search(sentence))
        if outbound_first_person or _OUTBOUND_BARE_RESULT.search(sentence):
            reason = _outbound_reason(sentence, records, first_person=outbound_first_person, user_text=user_text)
            if reason is not None:
                return reason

        if _EDIT_CLAIM_ZH.search(sentence) or _EDIT_CLAIM_EN.search(sentence):
            reason = _edit_reason(sentence, records, user_text=user_text)
            if reason is not None:
                return reason

    return None


def has_completion_claim(assistant_text: str) -> bool:
    """True when the answer makes a completion claim, whatever its evidence.

    Used by the disclosure policy: the PLAN badge is only informative when the
    turn actually claims something (an unbacked claim is the gap worth showing).
    """
    if not assistant_text.strip():
        return False
    for sentence in _sentences(assistant_text):
        if sentence.endswith(("?", "？")) or _excluded(sentence):
            continue
        if (
            _VERIFICATION_FIRST_PERSON.search(sentence)
            or _VERIFICATION_RESULT_ZH.search(sentence)
            or _VERIFICATION_RESULT_EN.search(sentence)
            or _OUTBOUND_FIRST_PERSON.search(sentence)
            or _OUTBOUND_BARE_RESULT.search(sentence)
            or _EDIT_CLAIM_ZH.search(sentence)
            or _EDIT_CLAIM_EN.search(sentence)
        ):
            return True
    return False


__all__ = ["check_execution_claim", "has_completion_claim"]
