"""Intake dangerous-intent safety router — re-exported from core.security.detection.intent_router.

[INPUT]
- core.security.detection.intent_router::DangerousIntent, IntentSafetyResult,
  scan_dangerous_intent (POS: 危险意图路由权威实现层)

[OUTPUT]
- DangerousIntent, IntentSafetyResult, scan_dangerous_intent (re-exported)

[POS]
Intake-facing alias of the core dangerous-intent router. The authoritative implementation is
core/security/detection/intent_router.py; this module exists so agent-layer intake code can
import the guard from the security namespace without depending on core paths directly.
"""

from myrm_agent_harness.core.security.detection.intent_router import (
    DangerousIntent as DangerousIntent,
)
from myrm_agent_harness.core.security.detection.intent_router import (
    IntentSafetyResult as IntentSafetyResult,
)
from myrm_agent_harness.core.security.detection.intent_router import (
    scan_dangerous_intent as scan_dangerous_intent,
)
