"""
[INPUT]: Active cron job configurations, run statuses, and schedule timestamps.
[OUTPUT]: Strongly-typed health models and full fleet doctor diagnostic reports.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/cron_doctor/models.py
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional


class CronHealthIssueCategory(str, Enum):
    """The 6 fundamental health check criteria for cron fleet jobs."""

    EXECUTION_FAILED = "EXECUTION_FAILED"  # Last execution failed with error
    DELIVERY_FAILED = "DELIVERY_FAILED"  # Delivery notification failed
    DELIVERY_UNVERIFIED = "DELIVERY_UNVERIFIED"  # Missing 3rd-party delivery receipt/ack
    SCHEDULE_OVERDUE = "SCHEDULE_OVERDUE"  # next_run_at is overdue (>10 mins behind current time)
    SCRIPT_INTEGRITY_ERROR = "SCRIPT_INTEGRITY_ERROR"  # Script file missing or unreadable
    WORKDIR_NOT_FOUND = "WORKDIR_NOT_FOUND"  # Sandbox workspace directory does not exist


@dataclass(frozen=True)
class CronJobHealthCheckTarget:
    """Read-only snapshot of a cron job and its runtime references for health inspection."""

    job_id: str
    job_name: str
    enabled: bool
    last_run_status: str  # "success", "failed", "running", "none"
    last_run_error: Optional[str] = None
    last_delivery_status: Optional[str] = None  # "delivered", "failed", "none"
    delivery_receipt_verified: bool = True
    next_run_at: Optional[float] = None  # Epoch timestamp in seconds
    script_path: Optional[str] = None
    workdir_path: Optional[str] = None


@dataclass(frozen=True)
class CronJobHealthIssue:
    """An actionable defect identified during a fleet health inspection."""

    job_id: str
    job_name: str
    category: CronHealthIssueCategory
    severity: str  # "WARNING", "CRITICAL"
    message: str
    suggested_fix: str
    details: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "job_id": self.job_id,
            "job_name": self.job_name,
            "category": self.category.value,
            "severity": self.severity,
            "message": self.message,
            "suggested_fix": self.suggested_fix,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class CronFleetDoctorReport:
    """Comprehensive read-only diagnostic dossier of the active cron job fleet."""

    total_jobs: int
    healthy_jobs_count: int
    issues_count: int
    is_fleet_healthy: bool
    issues: List[CronJobHealthIssue]
    inspected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, object]:
        return {
            "total_jobs": self.total_jobs,
            "healthy_jobs_count": self.healthy_jobs_count,
            "issues_count": self.issues_count,
            "is_fleet_healthy": self.is_fleet_healthy,
            "issues": [issue.to_dict() for issue in self.issues],
            "inspected_at": self.inspected_at,
        }
