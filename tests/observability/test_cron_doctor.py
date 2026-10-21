"""
Tests for CronFleetDoctor inspection engine and the 6 health gates.
"""

from myrm_agent_harness.observability.cron_doctor.doctor import CronFleetDoctor
from myrm_agent_harness.observability.cron_doctor.models import (
    CronFleetDoctorReport,
    CronHealthIssueCategory,
    CronJobHealthCheckTarget,
    CronJobHealthIssue,
)


def test_cron_fleet_doctor_all_healthy() -> None:
    doctor = CronFleetDoctor(path_exists_checker=lambda _: True)

    targets = [
        CronJobHealthCheckTarget(
            job_id="cron-01",
            job_name="Daily DB Backup",
            enabled=True,
            last_run_status="success",
            last_delivery_status="delivered",
            delivery_receipt_verified=True,
            next_run_at=1000.0,
            script_path="/opt/scripts/backup.sh",
            workdir_path="/var/sandbox/data",
        ),
        CronJobHealthCheckTarget(
            job_id="cron-02",
            job_name="Hourly Stock Sync",
            enabled=True,
            last_run_status="success",
            last_delivery_status=None,
            delivery_receipt_verified=True,
            next_run_at=1050.0,
        ),
    ]

    report = doctor.diagnose_fleet(targets, now_ts=950.0)

    assert report.total_jobs == 2
    assert report.healthy_jobs_count == 2
    assert report.issues_count == 0
    assert report.is_fleet_healthy is True
    assert len(report.issues) == 0


def test_cron_fleet_doctor_six_health_gates_detection() -> None:
    # Custom exists checker: returns False for paths containing "missing"
    def mock_exists(p: str) -> bool:
        return "missing" not in p

    doctor = CronFleetDoctor(
        schedule_overdue_threshold_secs=600.0,
        path_exists_checker=mock_exists,
    )
    now_ts = 2000.0

    targets = [
        # Gate 1: Execution Failed
        CronJobHealthCheckTarget(
            job_id="job-err-1",
            job_name="Sync Invoices",
            enabled=True,
            last_run_status="failed",
            last_run_error="Socket timeout connecting to SAP",
        ),
        # Gate 2: Delivery Failed
        CronJobHealthCheckTarget(
            job_id="job-del-2",
            job_name="Alert Dispatcher",
            enabled=True,
            last_run_status="success",
            last_delivery_status="failed",
        ),
        # Gate 3: Delivery Unverified
        CronJobHealthCheckTarget(
            job_id="job-unv-3",
            job_name="Webhooks Dispatcher",
            enabled=True,
            last_run_status="success",
            last_delivery_status="delivered",
            delivery_receipt_verified=False,
        ),
        # Gate 4: Schedule Overdue (>600s late)
        CronJobHealthCheckTarget(
            job_id="job-late-4",
            job_name="Stalled Cron Thread",
            enabled=True,
            last_run_status="success",
            next_run_at=1200.0,  # 800s overdue (2000 - 1200)
        ),
        # Gate 5: Script Integrity Error
        CronJobHealthCheckTarget(
            job_id="job-script-5",
            job_name="Missing Python Job",
            enabled=True,
            last_run_status="none",
            script_path="/opt/missing_script.py",
        ),
        # Gate 6: Workdir Not Found
        CronJobHealthCheckTarget(
            job_id="job-workdir-6",
            job_name="Lost Workspace Job",
            enabled=True,
            last_run_status="none",
            workdir_path="/data/missing_workspace",
        ),
    ]

    report = doctor.diagnose_fleet(targets, now_ts=now_ts)

    assert report.total_jobs == 6
    assert report.healthy_jobs_count == 0
    assert report.issues_count == 6
    assert report.is_fleet_healthy is False

    categories = [issue.category for issue in report.issues]
    assert CronHealthIssueCategory.EXECUTION_FAILED in categories
    assert CronHealthIssueCategory.DELIVERY_FAILED in categories
    assert CronHealthIssueCategory.DELIVERY_UNVERIFIED in categories
    assert CronHealthIssueCategory.SCHEDULE_OVERDUE in categories
    assert CronHealthIssueCategory.SCRIPT_INTEGRITY_ERROR in categories
    assert CronHealthIssueCategory.WORKDIR_NOT_FOUND in categories

    # Test serialization
    data = report.to_dict()
    assert data["total_jobs"] == 6
    assert data["issues_count"] == 6
    assert data["is_fleet_healthy"] is False
    assert len(data["issues"]) == 6
