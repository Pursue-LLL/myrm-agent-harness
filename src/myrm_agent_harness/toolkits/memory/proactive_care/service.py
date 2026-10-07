"""[POS]: src/myrm_agent_harness/toolkits/memory/proactive_care/service.py
[INPUT]: Health metrics records, conversational cues, and schedule task items.
[OUTPUT]: SQLite-backed proactive care lifecycle service with concurrency safety and cooldown gates.
"""

import json
import sqlite3
import threading
import time
from pathlib import Path

from myrm_agent_harness.toolkits.memory.proactive_care.evaluator import (
    VitalityAndFatigueEvaluator,
)
from myrm_agent_harness.toolkits.memory.proactive_care.models import (
    CareNotification,
    FatigueLevelKind,
    HealthMetricsRecord,
    ScheduleRebalancePlan,
    ScheduleTaskItem,
    VitalityAssessmentReport,
)
from myrm_agent_harness.toolkits.memory.proactive_care.rebalancer import (
    ProactiveScheduleRebalancer,
)


class ProactiveCareRebalancingService:
    """Thread-safe SQLite service orchestrating multi-modal vitality evaluation and schedule rebalancing."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        cooldown_seconds: float = 3600.0 * 12,  # 12 小时关怀冷却
    ) -> None:
        self._db_path = str(db_path)
        self._cooldown_seconds = cooldown_seconds
        self._lock = threading.Lock()
        self._evaluator = VitalityAndFatigueEvaluator()
        self._rebalancer = ProactiveScheduleRebalancer()

        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA busy_timeout = 5000;")
            self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS health_metrics (
            metric_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            sleep_duration_hours REAL NOT NULL,
            deep_sleep_ratio REAL NOT NULL,
            daily_steps INTEGER NOT NULL,
            resting_heart_rate INTEGER NOT NULL,
            recorded_at_iso TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS conversational_cues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            cue_text TEXT NOT NULL,
            timestamp REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS care_notifications (
            notification_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            fatigue_level TEXT NOT NULL,
            title TEXT NOT NULL,
            content_message TEXT NOT NULL,
            suggested_actions TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0
        );
        """)
        self._conn.commit()

    def sync_health_metrics(self, record: HealthMetricsRecord) -> HealthMetricsRecord:
        """Persist ingested health metrics telemetry."""
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO health_metrics (
                    metric_id, user_id, timestamp, sleep_duration_hours,
                    deep_sleep_ratio, daily_steps, resting_heart_rate, recorded_at_iso
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.metric_id,
                    record.user_id,
                    record.timestamp,
                    record.sleep_duration_hours,
                    record.deep_sleep_ratio,
                    record.daily_steps,
                    record.resting_heart_rate,
                    record.recorded_at_iso,
                ),
            )
            self._conn.commit()
        return record

    def record_conversational_cue(
        self, cue_text: str, user_id: str = "default_user"
    ) -> None:
        """Store casual fatigue cues mentioned in dialogues."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO conversational_cues (user_id, cue_text, timestamp) VALUES (?, ?, ?)",
                (user_id, cue_text.strip(), time.time()),
            )
            self._conn.commit()

    def get_recent_health_metrics(
        self, user_id: str = "default_user", limit: int = 7
    ) -> list[HealthMetricsRecord]:
        """Fetch recent physiological records sorted by timestamp ascending."""
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT metric_id, user_id, timestamp, sleep_duration_hours,
                       deep_sleep_ratio, daily_steps, resting_heart_rate, recorded_at_iso
                FROM health_metrics
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
            rows = cursor.fetchall()

        records: list[HealthMetricsRecord] = []
        for r in reversed(rows):
            records.append(
                HealthMetricsRecord(
                    metric_id=str(r["metric_id"]),
                    user_id=str(r["user_id"]),
                    timestamp=float(r["timestamp"]),
                    sleep_duration_hours=float(r["sleep_duration_hours"]),
                    deep_sleep_ratio=float(r["deep_sleep_ratio"]),
                    daily_steps=int(r["daily_steps"]),
                    resting_heart_rate=int(r["resting_heart_rate"]),
                    recorded_at_iso=str(r["recorded_at_iso"]),
                )
            )
        return records

    def get_recent_conversational_cues(
        self, user_id: str = "default_user", limit: int = 10
    ) -> list[str]:
        """Fetch recently logged conversation cues."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT cue_text FROM conversational_cues WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            )
            rows = cursor.fetchall()
        return [str(r["cue_text"]) for r in reversed(rows)]

    def evaluate_vitality(
        self, user_id: str = "default_user"
    ) -> VitalityAssessmentReport:
        """Evaluate current vitality report fusing stored hardware data and cues."""
        health_records = self.get_recent_health_metrics(user_id=user_id, limit=7)
        cues = self.get_recent_conversational_cues(user_id=user_id, limit=10)
        return self._evaluator.evaluate(
            health_records=health_records,
            conversational_cues=cues,
            user_id=user_id,
        )

    def rebalance_schedule_and_care(
        self,
        tasks: list[ScheduleTaskItem],
        user_id: str = "default_user",
        force_notify: bool = False,
    ) -> tuple[ScheduleRebalancePlan, CareNotification | None]:
        """Rebalance schedule tasks and emit care notification if not in cooldown."""
        report = self.evaluate_vitality(user_id=user_id)
        plan, notification = self._rebalancer.rebalance(
            report=report, tasks=tasks, user_id=user_id
        )

        should_deliver = force_notify
        if not should_deliver:
            last_notif = self._get_latest_notification(user_id=user_id)
            if last_notif is None:
                should_deliver = True
            elif last_notif.fatigue_level != notification.fatigue_level:
                # 状态严重度发生阶跃，必须推送
                should_deliver = True
            elif (time.time() - last_notif.timestamp) >= self._cooldown_seconds:
                # 冷却时间已过
                should_deliver = True

        delivered_notif: CareNotification | None = None
        if should_deliver:
            self._save_notification(notification)
            delivered_notif = notification

        return plan, delivered_notif

    def _get_latest_notification(
        self, user_id: str = "default_user"
    ) -> CareNotification | None:
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT notification_id, user_id, timestamp, fatigue_level,
                       title, content_message, suggested_actions, is_read
                FROM care_notifications
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (user_id,),
            )
            row = cursor.fetchone()

        if row is None:
            return None

        actions: list[str] = json.loads(str(row["suggested_actions"]))
        return CareNotification(
            notification_id=str(row["notification_id"]),
            user_id=str(row["user_id"]),
            timestamp=float(row["timestamp"]),
            fatigue_level=FatigueLevelKind(str(row["fatigue_level"])),
            title=str(row["title"]),
            content_message=str(row["content_message"]),
            suggested_actions=actions,
            is_read=bool(row["is_read"]),
        )

    def _save_notification(self, notif: CareNotification) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO care_notifications (
                    notification_id, user_id, timestamp, fatigue_level,
                    title, content_message, suggested_actions, is_read
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    notif.notification_id,
                    notif.user_id,
                    notif.timestamp,
                    notif.fatigue_level.value,
                    notif.title,
                    notif.content_message,
                    json.dumps(notif.suggested_actions, ensure_ascii=False),
                    1 if notif.is_read else 0,
                ),
            )
            self._conn.commit()

    def list_care_notifications(
        self, user_id: str = "default_user", unread_only: bool = False
    ) -> list[CareNotification]:
        """Query stored proactive care notifications."""
        query = (
            "SELECT notification_id, user_id, timestamp, fatigue_level, title, "
            "content_message, suggested_actions, is_read FROM care_notifications WHERE user_id = ?"
        )
        params: list[str | int] = [user_id]
        if unread_only:
            query += " AND is_read = 0"
        query += " ORDER BY timestamp DESC"

        with self._lock:
            cursor = self._conn.execute(query, params)
            rows = cursor.fetchall()

        results: list[CareNotification] = []
        for r in rows:
            results.append(
                CareNotification(
                    notification_id=str(r["notification_id"]),
                    user_id=str(r["user_id"]),
                    timestamp=float(r["timestamp"]),
                    fatigue_level=FatigueLevelKind(str(r["fatigue_level"])),
                    title=str(r["title"]),
                    content_message=str(r["content_message"]),
                    suggested_actions=json.loads(str(r["suggested_actions"])),
                    is_read=bool(r["is_read"]),
                )
            )
        return results

    def mark_notification_read(self, notification_id: str) -> bool:
        """Mark a proactive care notification as read."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE care_notifications SET is_read = 1 WHERE notification_id = ?",
                (notification_id,),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def close(self) -> None:
        """Close database connection."""
        with self._lock:
            self._conn.close()
