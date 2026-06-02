"""Cron scheduling toolkit.

Protocol-first design: the framework defines scheduling logic, CRUD management,
agent tools, and 5 protocols.  Concrete storage backends, agent runners,
delivery channels, and trigger providers are injected by the application layer.

Provides:
- CronScheduler: precise timer-based scheduling engine with watchdog and stagger
- CronManager: CRUD orchestration with validation and scheduler notification
- Heartbeat: one-call enable/disable for periodic agent self-checks
- ShellJobRunner: built-in runner for shell-type jobs
- InMemoryCronStore: built-in in-memory store for development and testing
- WebhookDelivery: built-in webhook delivery with HMAC signing
- Protocols: CronStore, JobRunner, ResultDelivery, ConcurrencyLock, TriggerProvider
- Triggers: EventTrigger, SystemEventTrigger, WebhookTrigger, PollTrigger


[INPUT]
- cron.delivery::WebhookDelivery (POS: webhook delivery with HMAC signing)
- cron.engine.scheduler::CronScheduler (POS: timer-based scheduling engine)
- cron.heartbeat (POS: periodic agent self-check utilities)
- cron.manager::CronManager (POS: cron CRUD orchestration layer)
- cron.protocols (POS: cron protocol definitions — store, runner, delivery, lock, trigger)
- cron.runners::ShellJobRunner (POS: built-in shell job runner)
- cron.stores::InMemoryCronStore (POS: in-memory store for dev/test)
- cron.situation (POS: Situation Report — pluggable context aggregator for heartbeat ticks)
- cron.triggers (POS: event trigger definitions)
- cron.types (POS: cron data models)

[OUTPUT]
- CronScheduler, CronManager: core scheduling components
- Heartbeat utilities: enable_heartbeat, disable_heartbeat, get_heartbeat_status, etc.
- Protocols: CronStore, JobRunner, ResultDelivery, ConcurrencyLock, TriggerProvider
- Built-in implementations: ShellJobRunner, InMemoryCronStore, WebhookDelivery
- Triggers: EventTrigger, SystemEventTrigger, WebhookTrigger, PollTrigger, TriggerConfig
- Situation Report: SituationSection, SituationReportBuilder, SituationContext
- Types: CronJob, CronJobPatch, CronConfig, JobStatus, JobType, ScheduleKind, etc.

[POS]
Cron toolkit entry point. Aggregates scheduling engine, CRUD manager, protocols, built-in
implementations, triggers, situation report aggregator, and data models for the protocol-first
cron framework.
"""

from myrm_agent_harness.toolkits.cron.delivery import WebhookDelivery
from myrm_agent_harness.toolkits.cron.engine.scheduler import CronScheduler
from myrm_agent_harness.toolkits.cron.heartbeat import (
    HEARTBEAT_JOB_NAME,
    HeartbeatStatus,
    disable_heartbeat,
    enable_heartbeat,
    get_heartbeat_status,
)
from myrm_agent_harness.toolkits.cron.manager import CronManager
from myrm_agent_harness.toolkits.cron.protocols import (
    ConcurrencyLock,
    CronStore,
    JobRunner,
    ResultDelivery,
    TriggerProvider,
)
from myrm_agent_harness.toolkits.cron.runners import RouterJobRunner, ShellJobRunner
from myrm_agent_harness.toolkits.cron.situation import (
    SituationContext,
    SituationReportBuilder,
    SituationSection,
)
from myrm_agent_harness.toolkits.cron.stores import InMemoryCronStore
from myrm_agent_harness.toolkits.cron.triggers import (
    EventTrigger,
    PollTrigger,
    SystemEventTrigger,
    TriggerConfig,
    TriggerKind,
    WebhookTrigger,
    dict_to_trigger_config,
    generate_webhook_path,
    generate_webhook_secret,
    trigger_config_to_dict,
)
from myrm_agent_harness.toolkits.cron.types import (
    CronConfig,
    CronJob,
    CronJobPatch,
    CronRunRecord,
    DeliveryConfig,
    DeliveryStatus,
    FailureAlertConfig,
    JobResult,
    JobStatus,
    JobType,
    RunStatus,
    Schedule,
    ScheduleKind,
    SessionTarget,
    TransientErrorKind,
)

__all__ = [
    "HEARTBEAT_JOB_NAME",
    "ConcurrencyLock",
    "CronConfig",
    "CronJob",
    "CronJobPatch",
    "CronManager",
    "CronRunRecord",
    "CronScheduler",
    "CronStore",
    "DeliveryConfig",
    "DeliveryStatus",
    "EventTrigger",
    "FailureAlertConfig",
    "HeartbeatStatus",
    "InMemoryCronStore",
    "JobResult",
    "JobRunner",
    "JobStatus",
    "JobType",
    "PollTrigger",
    "ResultDelivery",
    "RouterJobRunner",
    "RunStatus",
    "Schedule",
    "ScheduleKind",
    "SessionTarget",
    "ShellJobRunner",
    "SituationContext",
    "SituationReportBuilder",
    "SituationSection",
    "SystemEventTrigger",
    "TransientErrorKind",
    "TriggerConfig",
    "TriggerKind",
    "TriggerProvider",
    "WebhookDelivery",
    "WebhookTrigger",
    "dict_to_trigger_config",
    "disable_heartbeat",
    "enable_heartbeat",
    "generate_webhook_path",
    "generate_webhook_secret",
    "get_heartbeat_status",
    "trigger_config_to_dict",
]
