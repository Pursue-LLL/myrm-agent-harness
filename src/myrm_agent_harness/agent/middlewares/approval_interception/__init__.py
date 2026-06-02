"""Approval Interception Middleware.

Intercepts user text input when the agent is in a pending_approval state
and converts it into a Command(resume=...) to resume execution,
preventing the text from polluting the LLM context.
"""

from .interceptor import check_pending_approval, intercept_approval_text
from .recognizer import ApprovalIntent, ApprovalIntentRecognizer

__all__ = [
    "ApprovalIntent",
    "ApprovalIntentRecognizer",
    "check_pending_approval",
    "intercept_approval_text",
]
