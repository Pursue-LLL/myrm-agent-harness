# teams/

## Overview
Durable Agent Teams orchestration package.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Durable Agent Teams orchestration package. — Public export of types, engines, and errors for Durable Agent Teams | — |
| `engine.py` | Core | Durable Agent Team Engine coordinating Roster, CAS Task Graph, and Peer Mailbox. — DurableAgentTeamEngine: implicit root lead, kebab-case teammate spawning, CAS task flow, | ✅ |
| `mailbox.py` | Core | Durable Peer Mailbox with JSONL log persistence and cold recovery for Agent Teams. — DurablePeerMailbox: peer messaging, quiet/waking delivery, cold recovery, FIFO drain, rate limiting | ✅ |
| `task_graph.py` | Core | CAS Versioned Task Graph DAG engine for durable Agent Teams. — TaskGraphEngine: task CRUD, CAS optimistic lock, DAG cycle check, readiness, write scope warnings | ✅ |
| `types.py` | Types | Type definitions and models for Durable Agent Teams. — TeamMemberPhase, TeamMemberRole, TeamTaskStatus, DeliveryMode; TeamMemberSnapshot, TeamMessageSnapshot, TeamTaskSnapshot, TeamTaskView, TeamProjection; CASConflictError, TaskDependencyCycleError, TaskBlockedError | ✅ |
