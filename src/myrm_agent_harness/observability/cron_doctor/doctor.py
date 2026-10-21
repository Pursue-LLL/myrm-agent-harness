"""
[INPUT]: List of CronJobHealthCheckTarget instances and filesystem check callbacks.
[OUTPUT]: Actionable CronFleetDoctorReport with categorized issues and suggested remediations.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/cron_doctor/doctor.py
"""

from datetime import datetime, timezone
import os
import time
from typing import Callable, List, Optional

from .models import (
    CronFleetDoctorReport,
    CronHealthIssueCategory,
    CronJobHealthCheckTarget,
    CronJobHealthIssue,
)


class CronFleetDoctor:
    """
    Read-only fleet health inspector that evaluates cron automation tasks
    against the 6 core health gates.
    """

    def __init__(
        self,
        schedule_overdue_threshold_secs: float = 600.0,
        path_exists_checker: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self._overdue_threshold = schedule_overdue_threshold_secs
        self._exists_fn = path_exists_checker or os.path.exists

    def inspect_target(
        self,
        target: CronJobHealthCheckTarget,
        now_ts: float,
    ) -> List[CronJobHealthIssue]:
        """Runs the 6 health gates on a single cron job target."""
        issues: List[CronJobHealthIssue] = []

        # Gate 1: Execution Health
        if target.last_run_status.lower() == "failed":
            error_msg = target.last_run_error or "未捕获到具体错误根因"
            issues.append(
                CronJobHealthIssue(
                    job_id=target.job_id,
                    job_name=target.job_name,
                    category=CronHealthIssueCategory.EXECUTION_FAILED,
                    severity="CRITICAL",
                    message=f"上次执行失败：{error_msg}",
                    suggested_fix="检查任务执行日志与上下文变量，或手动触发单次重试",
                    details={"last_error": error_msg},
                )
            )

        # Gate 2: Delivery Health
        if target.last_delivery_status and target.last_delivery_status.lower() == "failed":
            issues.append(
                CronJobHealthIssue(
                    job_id=target.job_id,
                    job_name=target.job_name,
                    category=CronHealthIssueCategory.DELIVERY_FAILED,
                    severity="WARNING",
                    message="外部消息通知交付失败（Webhook 或邮件渠道未送达）",
                    suggested_fix="验证通知 Webhook URL 连通性或重新配置渠道秘钥凭据",
                )
            )

        # Gate 3: Receipt Health
        if (
            target.last_delivery_status
            and target.last_delivery_status.lower() == "delivered"
            and not target.delivery_receipt_verified
        ):
            issues.append(
                CronJobHealthIssue(
                    job_id=target.job_id,
                    job_name=target.job_name,
                    category=CronHealthIssueCategory.DELIVERY_UNVERIFIED,
                    severity="WARNING",
                    message="交付处于未验真状态（缺少第三方回执 ack 确认）",
                    suggested_fix="建议开启接收端验签回执或配置双向确认探针",
                )
            )

        # Gate 4: Schedule Liveness (Overdue schedule check)
        if target.enabled and target.next_run_at is not None:
            overdue_secs = now_ts - target.next_run_at
            if overdue_secs > self._overdue_threshold:
                issues.append(
                    CronJobHealthIssue(
                        job_id=target.job_id,
                        job_name=target.job_name,
                        category=CronHealthIssueCategory.SCHEDULE_OVERDUE,
                        severity="CRITICAL",
                        message=f"下次调度时间已逾期 {int(overdue_secs)} 秒（疑似调度器线程阻塞或卡死）",
                        suggested_fix="一键重置过期调度时间为当前时间或重启调度守护协程",
                        details={"overdue_seconds": str(int(overdue_secs))},
                    )
                )

        # Gate 5: Script Integrity
        if target.script_path:
            if not self._exists_fn(target.script_path):
                issues.append(
                    CronJobHealthIssue(
                        job_id=target.job_id,
                        job_name=target.job_name,
                        category=CronHealthIssueCategory.SCRIPT_INTEGRITY_ERROR,
                        severity="CRITICAL",
                        message=f"独立执行脚本文件不存在：{target.script_path}",
                        suggested_fix="恢复缺失的代码脚本文件或更新任务脚本引用路径",
                        details={"script_path": target.script_path},
                    )
                )

        # Gate 6: Environment Anchor (Workdir Check)
        if target.workdir_path:
            if not self._exists_fn(target.workdir_path):
                issues.append(
                    CronJobHealthIssue(
                        job_id=target.job_id,
                        job_name=target.job_name,
                        category=CronHealthIssueCategory.WORKDIR_NOT_FOUND,
                        severity="CRITICAL",
                        message=f"绑定的专属沙箱工作目录不存在：{target.workdir_path}",
                        suggested_fix="一键自动创建并初始化缺失的工作区目录或重新挂载 Volume",
                        details={"workdir_path": target.workdir_path},
                    )
                )

        return issues

    def diagnose_fleet(
        self,
        targets: List[CronJobHealthCheckTarget],
        now_ts: Optional[float] = None,
    ) -> CronFleetDoctorReport:
        """Inspects all targets in the fleet and compiles a diagnostic report."""
        current_time = now_ts if now_ts is not None else time.time()
        now_iso = datetime.now(timezone.utc).isoformat()

        all_issues: List[CronJobHealthIssue] = []
        jobs_with_issues = set()

        for target in targets:
            job_issues = self.inspect_target(target, current_time)
            if job_issues:
                all_issues.extend(job_issues)
                jobs_with_issues.add(target.job_id)

        total_jobs = len(targets)
        healthy_jobs_count = total_jobs - len(jobs_with_issues)

        return CronFleetDoctorReport(
            total_jobs=total_jobs,
            healthy_jobs_count=max(0, healthy_jobs_count),
            issues_count=len(all_issues),
            is_fleet_healthy=(len(all_issues) == 0),
            issues=all_issues,
            inspected_at=now_iso,
        )
