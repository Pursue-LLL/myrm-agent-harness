"""Suite orchestrating session handoff packaging, readonly sharing, secret gating, and line blame.

[INPUT]
- agent.context_management.session_handoff.secret_gate_scanner::SecretGateScanner (POS: Dual-tier secret gate
  scanner: storage masking placeholders and pre-publish scan blocking.)
- agent.context_management.session_handoff.session_blame_indexer::SessionBlameIndexer (POS: Indexer mapping
  source code lines back to originating session turns and prompt intents.)
- agent.context_management.session_handoff.session_handoff_types::HandoffMessageTurn, LineBlameEntry,
  LineBlameLookupResult, ReadonlyShareGrant, SecretGateScanResult, SessionHandoffPackage, ShareAccessStatus
  (POS: Types for session handoff package, readonly share grant, secret gate, and line blame.)

[OUTPUT]
- SessionHandoffPackageAndReadonlyShareAndSecretGateAndBlameSuite: End-to-end suite combining portable
  packaging, secure share grants, secret gates, and blame.

[POS]
Suite orchestrating session handoff packaging, readonly sharing, secret gating, and line blame.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .secret_gate_scanner import SecretGateScanner
from .session_blame_indexer import SessionBlameIndexer
from .session_handoff_types import (
    HandoffMessageTurn,
    LineBlameEntry,
    LineBlameLookupResult,
    ReadonlyShareGrant,
    SecretGateScanResult,
    SessionHandoffPackage,
    ShareAccessStatus,
)


class SessionHandoffPackageAndReadonlyShareAndSecretGateAndBlameSuite:
    """End-to-end suite combining portable packaging, secure share grants, secret gates, and blame."""

    def __init__(
        self,
        scanner: Optional[SecretGateScanner] = None,
        indexer: Optional[SessionBlameIndexer] = None,
    ) -> None:
        self._scanner = scanner or SecretGateScanner()
        self._indexer = indexer or SessionBlameIndexer()
        self._packages: Dict[str, SessionHandoffPackage] = {}
        self._grants_by_token: Dict[str, ReadonlyShareGrant] = {}
        self._grants_by_id: Dict[str, ReadonlyShareGrant] = {}

    @property
    def scanner(self) -> SecretGateScanner:
        """Access underlying secret gate scanner."""
        return self._scanner

    @property
    def blame_indexer(self) -> SessionBlameIndexer:
        """Access line-level blame indexer."""
        return self._indexer

    def create_handoff_package(
        self,
        session_id: str,
        creator_id: str,
        topic_summary: str,
        turns: List[HandoffMessageTurn],
        env_vars: Optional[Dict[str, str]] = None,
        workspace_snapshot_hash: str = "workspace-clean",
        auto_mask_secrets: bool = True,
    ) -> SessionHandoffPackage:
        """Package a session into a standalone bundle, enforcing pre-publish secret verification."""
        exported_envs = dict(env_vars or {})
        turn_texts = [turn.content for turn in turns]

        # Tier 2: Check release gate
        gate_res = self._scanner.scan_for_release_gate(texts=turn_texts, env_vars=exported_envs)
        if not gate_res.passed and not auto_mask_secrets:
            raise PermissionError(f"Handoff packaging blocked by secret gate: {gate_res.rejection_reason}")

        processed_turns: List[HandoffMessageTurn] = []
        for t in turns:
            content = self._scanner.mask_for_storage(t.content) if auto_mask_secrets else t.content
            processed_turns.append(
                HandoffMessageTurn(
                    turn_id=t.turn_id,
                    role=t.role,
                    content=content,
                    tool_calls_summary=t.tool_calls_summary,
                    artifacts_generated=t.artifacts_generated,
                )
            )

        processed_envs: Dict[str, str] = {}
        for k, v in exported_envs.items():
            processed_envs[k] = self._scanner.mask_for_storage(v) if auto_mask_secrets else v

        now_iso = datetime.now(timezone.utc).isoformat()
        raw_seed = f"{session_id}:{creator_id}:{len(processed_turns)}:{now_iso}"
        manifest_hash = hashlib.sha256(raw_seed.encode("utf-8")).hexdigest()
        package_id = f"pkg-{manifest_hash[:12]}"

        package = SessionHandoffPackage(
            package_id=package_id,
            session_id=session_id,
            creator_id=creator_id,
            topic_summary=topic_summary,
            created_at_iso=now_iso,
            manifest_hash=manifest_hash,
            turns=processed_turns,
            environment_variables_exported=processed_envs,
            workspace_snapshot_hash=workspace_snapshot_hash,
        )

        self._packages[package_id] = package
        return package

    def restore_handoff_package(self, package_id: str) -> SessionHandoffPackage:
        """Retrieve and restore a previously packaged session bundle."""
        if package_id not in self._packages:
            raise KeyError(f"Handoff package {package_id} not found")
        return self._packages[package_id]

    def create_readonly_share_grant(
        self,
        package_id: str,
        ttl_seconds: int = 86400,
        max_views: int = 10,
        password: Optional[str] = None,
    ) -> ReadonlyShareGrant:
        """Issue a cryptographic readonly share link with TTL, view limits, and optional password."""
        if package_id not in self._packages:
            raise KeyError(f"Cannot share non-existent package {package_id}")

        now = time.time()
        created_iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        expires_iso = datetime.fromtimestamp(now + ttl_seconds, tz=timezone.utc).isoformat()

        token_seed = f"{package_id}:{created_iso}:{ttl_seconds}"
        share_token = f"share-{hashlib.sha256(token_seed.encode('utf-8')).hexdigest()[:16]}"
        grant_id = f"grant-{hashlib.sha256(share_token.encode('utf-8')).hexdigest()[:10]}"

        pwd_hash = hashlib.sha256(password.encode("utf-8")).hexdigest() if password else None

        grant = ReadonlyShareGrant(
            grant_id=grant_id,
            package_id=package_id,
            share_url_token=share_token,
            created_at_iso=created_iso,
            expires_at_iso=expires_iso,
            max_views=max_views,
            current_views=0,
            password_hash=pwd_hash,
            is_revoked=False,
        )

        self._grants_by_token[share_token] = grant
        self._grants_by_id[grant_id] = grant
        return grant

    def access_readonly_share(
        self,
        share_url_token: str,
        password_attempt: Optional[str] = None,
    ) -> Tuple[ShareAccessStatus, Optional[SessionHandoffPackage]]:
        """Validate access conditions and return package if allowed, tracking view counts."""
        grant = self._grants_by_token.get(share_url_token)
        if not grant:
            return ShareAccessStatus.REVOKED, None

        if grant.is_revoked:
            return ShareAccessStatus.REVOKED, None

        expires_dt = datetime.fromisoformat(grant.expires_at_iso)
        if datetime.now(timezone.utc) > expires_dt:
            return ShareAccessStatus.EXPIRED, None

        if grant.current_views >= grant.max_views:
            return ShareAccessStatus.QUOTA_EXCEEDED, None

        if grant.password_hash is not None:
            if not password_attempt:
                return ShareAccessStatus.PASSWORD_REQUIRED, None
            attempt_hash = hashlib.sha256(password_attempt.encode("utf-8")).hexdigest()
            if attempt_hash != grant.password_hash:
                return ShareAccessStatus.INVALID_PASSWORD, None

        # Update view count
        updated_grant = ReadonlyShareGrant(
            grant_id=grant.grant_id,
            package_id=grant.package_id,
            share_url_token=grant.share_url_token,
            created_at_iso=grant.created_at_iso,
            expires_at_iso=grant.expires_at_iso,
            max_views=grant.max_views,
            current_views=grant.current_views + 1,
            password_hash=grant.password_hash,
            is_revoked=grant.is_revoked,
        )
        self._grants_by_token[share_url_token] = updated_grant
        self._grants_by_id[grant.grant_id] = updated_grant

        package = self._packages.get(grant.package_id)
        return ShareAccessStatus.GRANTED, package

    def revoke_readonly_share(self, grant_id: str) -> None:
        """Revoke an active share grant."""
        grant = self._grants_by_id.get(grant_id)
        if not grant:
            raise KeyError(f"Grant {grant_id} not found")

        revoked = ReadonlyShareGrant(
            grant_id=grant.grant_id,
            package_id=grant.package_id,
            share_url_token=grant.share_url_token,
            created_at_iso=grant.created_at_iso,
            expires_at_iso=grant.expires_at_iso,
            max_views=grant.max_views,
            current_views=grant.current_views,
            password_hash=grant.password_hash,
            is_revoked=True,
        )
        self._grants_by_token[grant.share_url_token] = revoked
        self._grants_by_id[grant_id] = revoked

    def record_line_blame(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
        session_id: str,
        turn_id: int,
        prompt_intent: str,
        timestamp_iso: str,
    ) -> LineBlameEntry:
        """Record line-level provenance linking code changes back to session turn."""
        return self._indexer.record_code_generation(
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            session_id=session_id,
            turn_id=turn_id,
            prompt_intent=prompt_intent,
            timestamp_iso=timestamp_iso,
        )

    def blame_code_line(self, file_path: str, line_number: int) -> LineBlameLookupResult:
        """Trace a code line back to its originating session context and intent."""
        return self._indexer.blame_line(file_path, line_number)
