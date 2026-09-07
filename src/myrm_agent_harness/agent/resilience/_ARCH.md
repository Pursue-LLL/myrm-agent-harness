"""# Marathon Task Resilience and Error Self-Correction Architecture

[INPUT]
- `myrm_agent_harness.agent.types`: CompletionStatus, AgentRunStatistics
- `myrm_agent_harness.agent.durable`: DurableStorageProtocol, TreeEntry, IntentRecord
- `myrm_agent_harness.utils.runtime.cancellation`: CancellationToken

[OUTPUT]
- `ErrorSelfCorrectionGovernor`: Autonomous diagnosis, hypothesis generation and error recovery engine for tool execution.
- `MarathonCheckpointer`: Long-running task checkpoint manager with crash recovery.
- `ExecutionBudgetGovernor`: Dynamic token budget, rate governor, and loop circuit breaker.

[POS]
Harness resilience subsystem providing multi-hour autonomous recovery, execution budgeting, and resilient state checkpointing.
"""
