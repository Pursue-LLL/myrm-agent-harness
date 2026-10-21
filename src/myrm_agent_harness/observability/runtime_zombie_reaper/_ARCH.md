# runtime_zombie_reaper/

## Overview
Agent process & causality tree dashboard, orphan process cascading reaper watchdog, deadlock polling active breaker, and cross-profile activity monitor suite.
Deeply inspired by Tony Simons' Hermes monitor, Mykyta Pavlenko's orphan helper process CPU leak bug, and Rompel's dead subagent deadlock polling trap.
Tracks PGID process trees across parent agents, delegated subagents, and helper processes (Playwright/Python/MCP), cascades SIGTERM/SIGKILL physical termination upon agent detach, and injects failure faults to interrupt infinite polling.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | Public re-exports of causality tracker and data models. | ✅ |
| `models.py` | Domain Models | Pydantic schemas for ProcessCausalityNode, ProfileResourceUsage, PostMortemTaskEntry, and RuntimeCausalitySnapshot. | ✅ |
| `tracker.py` | Core Tracker | AgentRuntimeCausalityTracker managing process trees, orphan reaping, deadlock detection, and failed runs. | ✅ |
