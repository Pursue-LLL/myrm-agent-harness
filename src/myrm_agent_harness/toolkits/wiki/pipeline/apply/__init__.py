"""Wiki apply pipeline — narrow-write mutations through WPG."""

from .errors import WikiApplyError
from .service import apply_wiki_mutation
from .types import WikiApplyOp, WikiApplyRequest, WikiApplyResult

__all__ = [
    "WikiApplyError",
    "WikiApplyOp",
    "WikiApplyRequest",
    "WikiApplyResult",
    "apply_wiki_mutation",
]
