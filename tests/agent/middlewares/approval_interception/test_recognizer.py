import pytest

from myrm_agent_harness.agent.middlewares.approval_interception.recognizer import (
    ApprovalIntent,
    ApprovalIntentRecognizer,
)


class TestApprovalIntentRecognizer:
    @pytest.mark.parametrize(
        "text, expected_intent",
        [
            ("y", ApprovalIntent.APPROVE),
            ("yes", ApprovalIntent.APPROVE),
            ("ok", ApprovalIntent.APPROVE),
            ("同意", ApprovalIntent.APPROVE),
            ("确认", ApprovalIntent.APPROVE),
            ("继续", ApprovalIntent.APPROVE),
            ("好", ApprovalIntent.APPROVE),
            ("好的", ApprovalIntent.APPROVE),
            ("approve", ApprovalIntent.APPROVE),
            ("accept", ApprovalIntent.APPROVE),
            (" YES ", ApprovalIntent.APPROVE),  # Test stripping and case
            ("Ok", ApprovalIntent.APPROVE),
            ("好，你继续吧", ApprovalIntent.APPROVE),
            ("好的，继续", ApprovalIntent.APPROVE),
            ("可以，继续吧", ApprovalIntent.APPROVE),
            ("没问题！", ApprovalIntent.APPROVE),
            ("行.", ApprovalIntent.APPROVE),
        ],
    )
    def test_recognize_approve(self, text: str, expected_intent: ApprovalIntent):
        intent, feedback = ApprovalIntentRecognizer.recognize(text)
        assert intent == expected_intent
        assert feedback is None

    @pytest.mark.parametrize(
        "text, expected_intent",
        [
            ("n", ApprovalIntent.REJECT),
            ("no", ApprovalIntent.REJECT),
            ("拒绝", ApprovalIntent.REJECT),
            ("取消", ApprovalIntent.REJECT),
            ("停止", ApprovalIntent.REJECT),
            ("否", ApprovalIntent.REJECT),
            ("reject", ApprovalIntent.REJECT),
            ("deny", ApprovalIntent.REJECT),
            ("cancel", ApprovalIntent.REJECT),
            (" No ", ApprovalIntent.REJECT),
            ("N", ApprovalIntent.REJECT),
            ("算了", ApprovalIntent.REJECT),
            ("别弄了", ApprovalIntent.REJECT),
            ("不要", ApprovalIntent.REJECT),
            ("算了，别弄了", ApprovalIntent.REJECT),
            ("不要吧", ApprovalIntent.REJECT),
        ],
    )
    def test_recognize_reject(self, text: str, expected_intent: ApprovalIntent):
        intent, feedback = ApprovalIntentRecognizer.recognize(text)
        assert intent == expected_intent
        assert feedback is None

    @pytest.mark.parametrize(
        "text, expected_intent",
        [
            ("always", ApprovalIntent.APPROVE_ALWAYS),
            ("总是允许", ApprovalIntent.APPROVE_ALWAYS),
            ("approve_always", ApprovalIntent.APPROVE_ALWAYS),
            ("always_allow", ApprovalIntent.APPROVE_ALWAYS),
            (" ALWAYS ", ApprovalIntent.APPROVE_ALWAYS),
        ],
    )
    def test_recognize_always(self, text: str, expected_intent: ApprovalIntent):
        intent, feedback = ApprovalIntentRecognizer.recognize(text)
        assert intent == expected_intent
        assert feedback is None

    @pytest.mark.parametrize(
        "text",
        [
            "yes, but change the path",
            "no, do something else",
            "I am not sure",
            "what does this mean?",
            "hello",
            "123",
            "",
            " ",
        ],
    )
    def test_recognize_feedback(self, text: str):
        intent, feedback = ApprovalIntentRecognizer.recognize(text)
        assert intent == ApprovalIntent.FEEDBACK
        assert feedback == text
