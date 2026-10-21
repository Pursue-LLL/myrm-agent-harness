"""Wiki apply pipeline — narrow-write mutations through WPG.

[INPUT]
- .errors::WikiApplyError (POS: structured apply errors)
- .service::apply_wiki_mutation (POS: vault lock + publish gate orchestration)
- .types::WikiApplyOp, WikiApplyRequest, WikiApplyResult (POS: apply contracts)

[OUTPUT]
- WikiApplyError, WikiApplyOp, WikiApplyRequest, WikiApplyResult, apply_wiki_mutation

[POS]
Wiki Apply 细粒度修改管道入口。通过受控的 Section 合约与 WPG 发布门禁执行精准知识库更新。
"""

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
