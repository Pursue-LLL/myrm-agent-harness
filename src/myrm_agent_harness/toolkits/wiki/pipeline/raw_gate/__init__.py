"""Raw publication gate — guarded writes to vault raw/.

[INPUT]
- .errors::RawGateError (POS: structured raw gate errors)
- .forget::ForgetEvidenceResult, forget_evidence, scan_existing_raw_vault (POS: evidence forgetting operations)
- .service::publish_raw (POS: guarded raw write service)
- .types::RawConflictPolicy, RawPublishRequest, RawPublishResult (POS: data contracts)

[OUTPUT]
- ForgetEvidenceResult, RawConflictPolicy, RawGateError, RawPublishRequest, RawPublishResult, forget_evidence, publish_raw, scan_existing_raw_vault

[POS]
Raw Gate 原始材料发布门禁入口。提供原子写入、冲突策略、安全前检以及关联证据遗忘。
"""

from .errors import RawGateError
from .forget import ForgetEvidenceResult, forget_evidence, scan_existing_raw_vault
from .service import publish_raw
from .types import RawConflictPolicy, RawPublishRequest, RawPublishResult

__all__ = [
    "ForgetEvidenceResult",
    "RawConflictPolicy",
    "RawGateError",
    "RawPublishRequest",
    "RawPublishResult",
    "forget_evidence",
    "publish_raw",
    "scan_existing_raw_vault",
]
