# ============================================================================
# SharedCloudSessionHub (Item 153)
# Production-grade collaborative shared session engine: token issuing,
# PII/credential sanitization, collaborative annotations & mid-flight steering.
# ============================================================================

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
import uuid

from .collaboration_types import (
    ArtifactInlineAnnotation,
    SanitizedMessage,
    ShareAccessLevel,
    SharedSessionSnapshot,
    SharedSessionToken,
    SteeringDirective,
)

logger = logging.getLogger(__name__)

# Sensitive credential and private path redaction regexes
_REDACTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(sk-[A-Za-z0-9_-]{20,})"),
    re.compile(r"(Bearer\s+[A-Za-z0-9_\-\.]{20,})", re.IGNORECASE),
    re.compile(r"(password\s*[:=]\s*['\"][^'\"]+['\"])", re.IGNORECASE),
    re.compile(r"/Users/[A-Za-z0-9_.-]+"),
    re.compile(r"/home/[A-Za-z0-9_.-]+"),
)


class SharedCloudSessionHub:
    """Manages shared cloud session snapshots, security gates, and team steering."""

    def __init__(self, secret_salt: str = "myrm-collab-default-salt") -> None:
        self._secret_salt = secret_salt
        self._tokens_by_id: dict[str, SharedSessionToken] = {}
        self._snapshots_by_share_id: dict[str, SharedSessionSnapshot] = {}
        self._annotations_by_share: dict[str, list[ArtifactInlineAnnotation]] = {}
        self._steering_queue_by_session: dict[str, list[SteeringDirective]] = {}

    def _compute_token_hash(self, token_id: str, session_id: str, level: ShareAccessLevel) -> str:
        """Computes HMAC-SHA256 signature for token authenticity verification."""
        msg = f"{token_id}:{session_id}:{level}".encode("utf-8")
        return hmac.new(self._secret_salt.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    def sanitize_text(self, text: str) -> tuple[str, bool]:
        """Redacts credentials, tokens, and local private directory paths from text."""
        sanitized = text
        was_redacted = False

        for pattern in _REDACTION_PATTERNS:
            if pattern.search(sanitized):
                was_redacted = True
                if "sk-" in pattern.pattern or "Bearer" in pattern.pattern:
                    sanitized = pattern.sub("[REDACTED_API_KEY]", sanitized)
                elif "password" in pattern.pattern:
                    sanitized = pattern.sub("password: [REDACTED_SECRET]", sanitized)
                else:
                    sanitized = pattern.sub("/workspace/user", sanitized)

        return sanitized, was_redacted

    def issue_share_token(
        self,
        session_id: str,
        access_level: ShareAccessLevel,
        duration_seconds: int = 86400,
        created_by: str = "session_owner",
    ) -> SharedSessionToken:
        """Issues an authenticated share token with strict permission bounds and expiry."""
        token_id = f"stok-{uuid.uuid4().hex[:12]}"
        now = time.time()
        expires_at = now + duration_seconds
        sig = self._compute_token_hash(token_id, session_id, access_level)

        token = SharedSessionToken(
            token_id=token_id,
            session_id=session_id,
            access_level=access_level,
            expires_at=expires_at,
            created_by=created_by,
            secret_hash=sig,
            created_at=now,
        )
        self._tokens_by_id[token_id] = token
        return token

    def verify_token(self, token_id: str, current_time: float | None = None) -> tuple[bool, str, SharedSessionToken | None]:
        """Validates token authenticity, signature integrity, and expiration."""
        token = self._tokens_by_id.get(token_id)
        if not token:
            return False, "Token not found", None

        if token.is_expired(current_time):
            return False, "Token has expired", token

        expected_sig = self._compute_token_hash(token.token_id, token.session_id, token.access_level)
        if not hmac.compare_digest(token.secret_hash, expected_sig):
            return False, "Invalid cryptographic token signature", None

        return True, "Token valid", token

    def generate_share_snapshot(
        self,
        session_id: str,
        raw_messages: list[dict[str, str]],
        title: str,
        access_level: ShareAccessLevel,
        public_artifact_ids: list[str] | None = None,
        duration_seconds: int = 86400,
    ) -> SharedSessionSnapshot:
        """Constructs a public sanitized transcript snapshot free of private assets."""
        share_id = f"share-{uuid.uuid4().hex[:12]}"
        sanitized_msgs: list[SanitizedMessage] = []

        for idx, m in enumerate(raw_messages):
            raw_content = m.get("content", "")
            sanitized_content, was_red = self.sanitize_text(raw_content)
            raw_thought = m.get("thought", "")
            sanitized_thought, thought_red = self.sanitize_text(raw_thought)

            msg = SanitizedMessage(
                message_id=m.get("id", f"msg-{idx}"),
                role=m.get("role", "user"),
                content=sanitized_content,
                thought_trace=sanitized_thought,
                timestamp=time.time(),
                was_redacted=was_red or thought_red,
            )
            sanitized_msgs.append(msg)

        now = time.time()
        snapshot = SharedSessionSnapshot(
            share_id=share_id,
            session_id=session_id,
            title=title,
            access_level=access_level,
            messages=sanitized_msgs,
            annotations=[],
            public_artifact_ids=list(public_artifact_ids or []),
            expires_at=now + duration_seconds,
            created_at=now,
        )

        self._snapshots_by_share_id[share_id] = snapshot
        self._annotations_by_share[share_id] = []
        return snapshot

    def add_inline_annotation(
        self,
        share_id: str,
        token: SharedSessionToken,
        artifact_id: str,
        line_start: int,
        line_end: int,
        comment_text: str,
    ) -> ArtifactInlineAnnotation:
        """Adds a team review annotation if the token holds comment or steering permissions."""
        if token.access_level == ShareAccessLevel.READ_ONLY:
            raise PermissionError("READ_ONLY access level does not permit adding annotations")

        snapshot = self._snapshots_by_share_id.get(share_id)
        if not snapshot:
            raise KeyError(f"Share snapshot not found: {share_id}")

        anno_id = f"anno-{uuid.uuid4().hex[:8]}"
        annotation = ArtifactInlineAnnotation(
            annotation_id=anno_id,
            artifact_id=artifact_id,
            line_start=line_start,
            line_end=line_end,
            author=token.created_by,
            comment_text=comment_text,
            created_at=time.time(),
        )

        snapshot.annotations.append(annotation)
        self._annotations_by_share.setdefault(share_id, []).append(annotation)
        return annotation

    def inject_steering_directive(
        self,
        session_id: str,
        token: SharedSessionToken,
        directive_text: str,
    ) -> SteeringDirective:
        """Injects collaborative steering guidance into an active session."""
        if token.access_level != ShareAccessLevel.INTERACTIVE_STEERING:
            raise PermissionError("INTERACTIVE_STEERING permission is required to steer the session")

        if token.session_id != session_id:
            raise ValueError(f"Token is not authorized for session {session_id}")

        directive = SteeringDirective(
            directive_id=f"dir-{uuid.uuid4().hex[:8]}" ,
            session_id=session_id,
            author=token.created_by,
            directive_text=directive_text.strip(),
            applied_to_context=False,
            injected_at=time.time(),
        )

        self._steering_queue_by_session.setdefault(session_id, []).append(directive)
        return directive

    def build_steering_context_block(self, session_id: str, consume: bool = True) -> str:
        """Builds XML context block injecting pending team steering guidance into Agent turn."""
        queue = self._steering_queue_by_session.get(session_id, [])
        unconsumed = [d for d in queue if not d.applied_to_context]

        if not unconsumed:
            return ""

        lines: list[str] = [
            '<collaborative_team_steering priority="HIGH">',
            "### 👥 来自团队协同者的实时中途指导建议 (Mid-Flight Guidance)：",
        ]

        for d in unconsumed:
            lines.append(f"- **来自协同者 @{d.author}**：{d.directive_text}")
            if consume:
                d.applied_to_context = True

        lines.append(
            "请以专业态度审视上述团队协同意见，在后续动作中充分权衡并吸收建议。"
        )
        lines.append("</collaborative_team_steering>")
        return "\n".join(lines)

    def get_snapshot(self, share_id: str) -> SharedSessionSnapshot | None:
        """Retrieves a cached share snapshot by ID."""
        return self._snapshots_by_share_id.get(share_id)
