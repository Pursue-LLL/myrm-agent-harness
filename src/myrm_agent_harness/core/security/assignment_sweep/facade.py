"""
[POS] src/myrm_agent_harness/core/security/assignment_sweep/facade.py
[INPUT] typing, types, quoted_sweep_engine, database_url_auditor
[OUTPUT] QuotedKeySecretAssignmentSweepFacade
Unified facade for quoted-key secret assignment sweeps, separator prefix detection, and DSN auditing.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .database_url_auditor import DatabaseUrlAuditor
from .quoted_sweep_engine import QuotedKeySecretAssignmentSweepEngine
from .types import (
    AssignmentSweepReport,
    AssignmentSweepVerdict,
    DatabaseUrlAuditResult,
)

logger = logging.getLogger(__name__)


class QuotedKeySecretAssignmentSweepFacade:
    """Unified entrypoint for quoted-key assignment sweeps and loopback DSN audit policies."""

    def __init__(
        self,
        engine: QuotedKeySecretAssignmentSweepEngine | None = None,
        dsn_auditor: DatabaseUrlAuditor | None = None,
    ) -> None:
        self._dsn_auditor = dsn_auditor or DatabaseUrlAuditor()
        self._engine = engine or QuotedKeySecretAssignmentSweepEngine(self._dsn_auditor)

    @property
    def engine(self) -> QuotedKeySecretAssignmentSweepEngine:
        """Underlying assignment sweep engine."""
        return self._engine

    @property
    def dsn_auditor(self) -> DatabaseUrlAuditor:
        """Underlying database URL auditor."""
        return self._dsn_auditor

    def sweep_text(self, content: str) -> AssignmentSweepReport:
        """Perform full sweep over text content, extracting quoted secrets and auditing DSNs."""
        return self._engine.scan_content(content)

    def audit_database_url(self, raw_url: str) -> DatabaseUrlAuditResult | None:
        """Evaluate a single database connection string for loopback exemption or leak risk."""
        return self._dsn_auditor.audit_url(raw_url)

    def is_clean(self, content: str) -> bool:
        """Return True if content contains zero active unexempted credential exposures."""
        report = self.sweep_text(content)
        return report.verdict in {
            AssignmentSweepVerdict.CLEAN,
            AssignmentSweepVerdict.EXEMPTED_LOCAL_DEV,
        }
