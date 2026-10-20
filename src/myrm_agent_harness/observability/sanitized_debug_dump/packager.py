"""
[INPUT]: Raw logs, trace events, user notes, and platform vitals.
[OUTPUT]: Immutable SanitizedDebugDump instances, secure SHA256 checksums, and EphemeralShareLink tokens.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/sanitized_debug_dump/packager.py
"""

from datetime import datetime, timedelta, timezone
import hashlib
import os
import platform
import secrets
import sys
import threading
from typing import Dict, List, Optional, Tuple

from .models import (
    EphemeralShareLink,
    RedactionAuditRecord,
    SanitizedDebugDump,
    SystemVitalsSnapshot,
)
from .redactor import ZeroLeakRedactor


class SanitizedDebugPackager:
    """
    Collects system runtime vitals, scrubs logs and traces using ZeroLeakRedactor,
    and manages ephemeral self-destructing debug share links.
    """

    def __init__(self, share_ttl_hours: int = 48, max_views_before_burn: int = 3) -> None:
        self._lock = threading.Lock()
        self._redactor = ZeroLeakRedactor()
        self._share_ttl_hours = share_ttl_hours
        self._max_views_before_burn = max_views_before_burn
        self._dumps: Dict[str, SanitizedDebugDump] = {}
        self._ephemeral_links: Dict[str, EphemeralShareLink] = {}

    def collect_vitals(self) -> SystemVitalsSnapshot:
        now_iso = datetime.now(timezone.utc).isoformat()
        os_info = f"{platform.system()} {platform.release()} ({platform.machine()})"
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        cpu_count = os.cpu_count() or 1

        return SystemVitalsSnapshot(
            os_name=os_info,
            python_version=py_ver,
            cpu_cores=cpu_count,
            memory_total_gb=16.0,  # Generic default or probed
            network_connectivity="CONNECTED",
            timestamp=now_iso,
        )

    def create_sanitized_dump(
        self,
        raw_logs: List[str],
        recent_traces: Optional[List[Dict[str, str]]] = None,
        user_note: str = "",
        custom_vitals: Optional[SystemVitalsSnapshot] = None,
    ) -> SanitizedDebugDump:
        dump_id = f"dump_{secrets.token_hex(8)}"
        vitals = custom_vitals or self.collect_vitals()

        # Sanitize logs
        s_logs, audits, total_redacted = self._redactor.sanitize_lines(raw_logs)
        audit_dict = {a.rule_type: (a.masked_placeholder, a.occurrences_count) for a in audits}

        # Sanitize traces
        s_traces: List[Dict[str, str]] = []
        if recent_traces:
            for trace in recent_traces:
                sanitized_trace: Dict[str, str] = {}
                for k, v in trace.items():
                    clean_v, t_audits = self._redactor.sanitize(str(v))
                    sanitized_trace[k] = clean_v
                    for a in t_audits:
                        total_redacted += a.occurrences_count
                        prev_cnt = audit_dict.get(a.rule_type, (a.masked_placeholder, 0))[1]
                        audit_dict[a.rule_type] = (a.masked_placeholder, prev_cnt + a.occurrences_count)
                s_traces.append(sanitized_trace)

        # Sanitize user note
        clean_note, note_audits = self._redactor.sanitize(user_note)
        for a in note_audits:
            total_redacted += a.occurrences_count
            prev_cnt = audit_dict.get(a.rule_type, (a.masked_placeholder, 0))[1]
            audit_dict[a.rule_type] = (a.masked_placeholder, prev_cnt + a.occurrences_count)

        combined_audits = [
            RedactionAuditRecord(
                rule_type=rule,
                masked_placeholder=placeholder,
                occurrences_count=cnt,
            )
            for rule, (placeholder, cnt) in audit_dict.items()
        ]

        now_iso = datetime.now(timezone.utc).isoformat()

        # Compute SHA256 checksum over sanitized payload
        hasher = hashlib.sha256()
        hasher.update(dump_id.encode("utf-8"))
        for line in s_logs:
            hasher.update(line.encode("utf-8"))
        checksum = hasher.hexdigest()

        dump = SanitizedDebugDump(
            dump_id=dump_id,
            vitals=vitals,
            sanitized_logs=s_logs,
            recent_traces=s_traces,
            redacted_audits=combined_audits,
            total_redacted_count=total_redacted,
            user_note=clean_note,
            checksum_sha256=checksum,
            created_at=now_iso,
        )

        with self._lock:
            self._dumps[dump_id] = dump

        return dump

    def create_ephemeral_link(
        self,
        dump_id: str,
        base_url: str = "https://debug.myrm.ai/share",
    ) -> EphemeralShareLink:
        with self._lock:
            if dump_id not in self._dumps:
                raise KeyError(f"Dump ID not found: {dump_id}")

            share_token = f"share_{secrets.token_urlsafe(16)}"
            now_dt = datetime.now(timezone.utc)
            expires_dt = now_dt + timedelta(hours=self._share_ttl_hours)

            link = EphemeralShareLink(
                share_token=share_token,
                dump_id=dump_id,
                share_url=f"{base_url}/{share_token}",
                expires_at=expires_dt.isoformat(),
                max_views=self._max_views_before_burn,
                remaining_views=self._max_views_before_burn,
                is_destroyed=False,
                created_at=now_dt.isoformat(),
            )
            self._ephemeral_links[share_token] = link
            return link

    def consume_ephemeral_link(
        self,
        share_token: str,
    ) -> Tuple[Optional[SanitizedDebugDump], Optional[str]]:
        """
        Consumes one view on an ephemeral share link.
        Returns:
            (SanitizedDebugDump | None, error_message | None)
        """
        with self._lock:
            if share_token not in self._ephemeral_links:
                return None, "分享链接不存在或已被阅后即焚彻底销毁"

            link = self._ephemeral_links[share_token]

            if link.is_destroyed:
                return None, "该分享包已达到最大查看次数并已自毁"

            # Check expiration
            expires_dt = datetime.fromisoformat(link.expires_at)
            if datetime.now(timezone.utc) > expires_dt:
                link.is_destroyed = True
                return None, "分享链接已超过 48 小时安全有效期"

            link.remaining_views -= 1
            if link.remaining_views <= 0:
                link.is_destroyed = True

            dump = self._dumps.get(link.dump_id)
            return dump, None

    def get_dump(self, dump_id: str) -> Optional[SanitizedDebugDump]:
        with self._lock:
            return self._dumps.get(dump_id)
