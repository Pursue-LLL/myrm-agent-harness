"""Four-dimensional operator transparency auditing and cryptographic profile signature verification."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

from myrm_agent_harness.core.security.sandbox_zero_leakage_pii.types import (
    AgentProfileSignature,
    FourDimensionalAuditScore,
    TransparencyTier,
)

logger = logging.getLogger(__name__)

_DEFAULT_SIGNING_KEY: bytes = b"myrm-agent-profile-authority-v1"

_OPAQUE_MODEL_PATTERNS = {"custom-ai", "smart-v1", "blackbox", "magic-llm", "proxy-model"}
_TRUSTED_ORGANIZATIONS = {"myrm", "pursue", "nous", "anthropic", "openai", "meta", "google"}


class OperatorTransparencyAuditor:
    """Audits third-party agent hosting transparency and provides official profile signatures."""

    def __init__(self, signing_secret: bytes | None = None) -> None:
        self._signing_secret: bytes = signing_secret or _DEFAULT_SIGNING_KEY

    def audit_operator(
        self,
        operator_name: str,
        base_model_id: str,
        data_jurisdiction: str,
        is_codebase_public: bool,
    ) -> FourDimensionalAuditScore:
        """Perform 4D transparency assessment across identity, model clarity, storage, and codebase."""
        warnings: list[str] = []

        # 1. Operator identity score
        op_lower = operator_name.strip().lower()
        if any(org in op_lower for org in _TRUSTED_ORGANIZATIONS):
            op_score = 1.0
        elif op_lower and op_lower not in ("anonymous", "unknown", ""):
            op_score = 0.7
        else:
            op_score = 0.1
            warnings.append("Operator identity is anonymous or unverified.")

        # 2. Model transparency score
        model_lower = base_model_id.strip().lower()
        if any(opaque in model_lower for opaque in _OPAQUE_MODEL_PATTERNS) or not model_lower:
            model_score = 0.2
            warnings.append("Underlying model ID is opaque or disguised; true lineage cannot be verified.")
        else:
            model_score = 1.0

        # 3. Data jurisdiction score
        jurisdiction_lower = data_jurisdiction.strip().lower()
        if jurisdiction_lower in ("local", "on-premise", "eu-gdpr", "us-east-1", "private-vpc"):
            jurisdiction_score = 1.0
        elif jurisdiction_lower in ("unknown", "unspecified", ""):
            jurisdiction_score = 0.2
            warnings.append("Data storage jurisdiction is unspecified, risking untracked cross-border transfer.")
        else:
            jurisdiction_score = 0.7

        # 4. Codebase auditability score
        if is_codebase_public:
            code_score = 1.0
        else:
            code_score = 0.3
            warnings.append("Host platform codebase is closed-source and cannot be independently audited.")

        overall = round(
            (op_score * 0.3) + (model_score * 0.3) + (jurisdiction_score * 0.2) + (code_score * 0.2),
            3,
        )

        if overall >= 0.85:
            tier = TransparencyTier.VERIFIED_TRANSPARENT
        elif overall >= 0.50:
            tier = TransparencyTier.MEDIUM_RISK
        else:
            tier = TransparencyTier.UNTRUSTED_BLACKBOX

        return FourDimensionalAuditScore(
            operator_identity_score=op_score,
            model_transparency_score=model_score,
            data_jurisdiction_score=jurisdiction_score,
            codebase_auditability_score=code_score,
            overall_score=overall,
            tier=tier,
            warnings=warnings,
        )

    def sign_agent_profile(
        self,
        profile_id: str,
        author: str,
        model_id: str,
        system_prompt: str,
        is_official: bool = True,
    ) -> AgentProfileSignature:
        """Issue cryptographic signature proving authentic agent profile origin."""
        now = time.time()
        prompt_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()

        body = json.dumps(
            {
                "profile_id": profile_id,
                "author": author,
                "model_id": model_id,
                "prompt_hash": prompt_hash,
                "is_official": is_official,
                "signed_at": int(now),
            },
            sort_keys=True,
        )

        signature = hmac.new(
            self._signing_secret,
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return AgentProfileSignature(
            profile_id=profile_id,
            author=author,
            model_id=model_id,
            system_prompt_hash=prompt_hash,
            signed_at=now,
            signature=signature,
            is_official_verified=is_official,
        )

    def verify_agent_profile(
        self,
        profile_pkg: AgentProfileSignature,
        actual_system_prompt: str,
    ) -> bool:
        """Verify profile integrity and authority signature against candidate system prompt."""
        expected_hash = hashlib.sha256(actual_system_prompt.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(profile_pkg.system_prompt_hash, expected_hash):
            logger.warning("System prompt hash mismatch for profile '%s'.", profile_pkg.profile_id)
            return False

        body = json.dumps(
            {
                "profile_id": profile_pkg.profile_id,
                "author": profile_pkg.author,
                "model_id": profile_pkg.model_id,
                "prompt_hash": profile_pkg.system_prompt_hash,
                "is_official": profile_pkg.is_official_verified,
                "signed_at": int(profile_pkg.signed_at),
            },
            sort_keys=True,
        )

        expected_sig = hmac.new(
            self._signing_secret,
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(profile_pkg.signature, expected_sig)
