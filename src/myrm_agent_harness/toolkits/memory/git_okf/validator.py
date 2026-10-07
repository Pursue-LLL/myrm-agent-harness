# [POS]: myrm_agent_harness/toolkits/memory/git_okf/validator.py
# [INPUT]: OKF concepts, declared bundle version, current date
# [OUTPUT]: Conformance audit, stale evaluation, human vs agent trust anti-tamper verification

import datetime
import posixpath
import re
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.git_okf.models import (
    ConceptStatus,
    GovernanceLevel,
    OKFConcept,
    OKFValidationReport,
)

_ISO_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_iso_timestamp(timestamp_str: str) -> datetime.datetime | None:
    """Safely parse common ISO 8601 timestamps."""
    cleaned = timestamp_str.strip()
    if not cleaned:
        return None
    # Support YYYY-MM-DD
    if _ISO_DATE_REGEX.match(cleaned):
        try:
            return datetime.datetime.strptime(cleaned, "%Y-%m-%d").replace(tzinfo=datetime.UTC)
        except ValueError:
            return None
    try:
        # datetime.fromisoformat handles RFC3339 / ISO 8601
        dt = datetime.datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.UTC)
        return dt
    except ValueError:
        return None


class OKFConceptValidator:
    """Strict validator implementing Google OKF v0.2 conformance checks,

    memory rot prevention (stale_after), human-agent trust balance,
    and path traversal (CWE-22) security screening.
    """

    def __init__(self, declared_version: str = "0.2") -> None:
        self._declared_version = declared_version

    def is_concept_stale(self, concept: OKFConcept, reference_date: datetime.date | None = None) -> bool:
        """Evaluate if concept has exceeded its explicit shelf life (stale_after)."""
        if not concept.stale_after or not _ISO_DATE_REGEX.match(concept.stale_after):
            return False
        today = reference_date or datetime.datetime.now(datetime.UTC).date()
        try:
            exp_date = datetime.date.fromisoformat(concept.stale_after)
            return today >= exp_date
        except ValueError:
            return False

    def validate(
        self,
        concepts: Sequence[OKFConcept],
        bundle_path: str = ".",
        reference_date: datetime.date | None = None,
    ) -> OKFValidationReport:
        """Run comprehensive OKF v0.2 audit over a collection of concepts."""
        report = OKFValidationReport(
            bundle_path=bundle_path,
            declared_version=self._declared_version,
            concept_count=len(concepts),
        )

        today = reference_date or datetime.datetime.now(datetime.UTC).date()

        for c in concepts:
            # 1. Structural Conformance
            if not c.type or not c.type.strip():
                report.errors.append(f"{c.path}: 'type' field is missing or empty")

            if not c.id or not c.id.strip():
                report.errors.append(f"{c.path}: 'id' field is missing or empty")

            # Governance validity
            if c.governance not in (GovernanceLevel.CONSTRAINT, GovernanceLevel.HOLD, GovernanceLevel.CONTEXT):
                report.gate_findings.append(
                    f"{c.id}: invalid governance level '{c.governance}', must be constraint|hold|context"
                )

            # Lifecycle status validity
            if c.status not in (ConceptStatus.DRAFT, ConceptStatus.STABLE, ConceptStatus.DEPRECATED):
                report.gate_findings.append(
                    f"{c.id}: invalid status '{c.status}', must be draft|stable|deprecated"
                )

            # 2. Memory Rot Prevention (stale_after)
            if c.stale_after:
                if not _ISO_DATE_REGEX.match(c.stale_after):
                    report.warnings.append(
                        f"{c.id}: stale_after '{c.stale_after}' is not valid YYYY-MM-DD"
                    )
                elif self.is_concept_stale(c, reference_date=today):
                    report.stale_count += 1
                    report.warnings.append(
                        f"{c.id}: concept is stale (stale_after {c.stale_after} <= {today.isoformat()})"
                    )

            # 3. CWE-22 Path Traversal Prevention on code_refs
            for ref in c.code_refs:
                norm_ref = posixpath.normpath(ref.strip().replace("\\", "/"))
                if posixpath.isabs(norm_ref) or norm_ref.startswith("/"):
                    report.gate_findings.append(
                        f"{c.id}: code_refs '{ref}' must be a relative workspace path"
                    )
                elif norm_ref == ".." or norm_ref.startswith("../") or "/../" in norm_ref:
                    report.gate_findings.append(
                        f"{c.id}: code_refs '{ref}' contains forbidden '..' directory traversal"
                    )

            # 4. Human-Agent Trust & Anti-Tamper Verification
            # If concept has verified entries and an agent generated block, ensure verification postdates generation
            if c.generated and c.generated.at:
                gen_dt = _parse_iso_timestamp(c.generated.at)
                if gen_dt is None:
                    report.warnings.append(
                        f"{c.id}: generated.at '{c.generated.at}' is not valid ISO 8601"
                    )
                for idx, v in enumerate(c.verified):
                    v_dt = _parse_iso_timestamp(v.at)
                    if v_dt is None:
                        report.warnings.append(
                            f"{c.id}: verified[{idx}].at '{v.at}' is not valid ISO 8601"
                        )
                    elif gen_dt and v_dt < gen_dt:
                        report.superseded_trust_count += 1
                        report.gate_findings.append(
                            f"{c.id}: verified[{idx}] by '{v.by}' at '{v.at}' predates generated.at '{c.generated.at}' (superseded verification)"
                        )

        report.is_conformant = len(report.errors) == 0
        report.gate_passed = len(report.errors) == 0 and len(report.gate_findings) == 0

        return report
