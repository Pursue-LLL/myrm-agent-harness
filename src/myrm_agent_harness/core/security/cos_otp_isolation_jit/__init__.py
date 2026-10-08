"""CoS Sensitive OTP Dynamic Isolation, Recovery Blackhole, and JIT Authorization Suite.

Protects personal chief-of-staff assistants against credential harvesting via prompt injection,
enforces recovery URL blackholes, provides burn-after-reading JIT authorization tickets,
and manages multi-tier quota watermark alerts with smooth fallback rails.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.cos_otp_isolation_jit.jit_gate import (
    IntentBoundJitAuthorizationGate,
)
from myrm_agent_harness.core.security.cos_otp_isolation_jit.otp_redactor import (
    SensitiveOtpRedactor,
)
from myrm_agent_harness.core.security.cos_otp_isolation_jit.quota_rails import (
    QuotaWatermarkGuard,
)
from myrm_agent_harness.core.security.cos_otp_isolation_jit.types import (
    BlackholeInspectionResult,
    JitOtpTicket,
    OtpRedactionResult,
    QuotaAssessment,
    QuotaWatermarkTier,
)

__all__ = [
    "BlackholeInspectionResult",
    "IntentBoundJitAuthorizationGate",
    "JitOtpTicket",
    "OtpRedactionResult",
    "QuotaAssessment",
    "QuotaWatermarkGuard",
    "QuotaWatermarkTier",
    "SensitiveOtpRedactor",
]
