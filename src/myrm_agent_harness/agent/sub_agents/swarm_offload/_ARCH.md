# swarm_offload/

## Overview
High-Concurrency Subagent Swarm and Adaptive Cloud Offload Package (Item 60).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | High-Concurrency Subagent Swarm and Adaptive Cloud Offload Package (Item 60). — Public module exports for Item 60 swarm dispatch and host resource preservation. | — |
| `offload_dispatcher.py` | Core | 10-15 Concurrency Swarm Dispatcher with Transparent Cloud Sandbox Offload (Item 60). — High-throughput parallel execution across local host and cloud sandboxes.; SwarmBatchSummary containing metrics, offload ratios, and artifact pointers. | ✅ |
| `types.py` | Types | Core types and data contracts for High-Concurrency Swarm & Adaptive Cloud Offload (Item 60). — OffloadStrategy, ExecutionTarget, WorkerState, TaskPriority, | ✅ |
| `watermark_monitor.py` | Core | Host physical resource watermark monitor and overload detector (Item 60). — Real-time ResourceWatermark snapshots and offload recommendations.; Peak usage statistics across a swarm dispatch session. | ✅ |
