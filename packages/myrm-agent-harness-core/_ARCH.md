# packages/myrm-agent-harness-core/

## Overview

Platform-specific wheel project for Nuitka-compiled core IP artifacts. Built by `scripts/build_core.py` via static hatch `force-include` (not hatch build hooks).

## File Index

| File | Role | Description |
|------|------|-------------|
| pyproject.toml | Core | Wheel metadata; `src/myrm_agent_harness_core` marker package |
| src/myrm_agent_harness_core/__init__.py | Core | Platform key marker; compiled `.so` land in `myrm_agent_harness/` namespace |

## System Design

See [DISTRIBUTION_SYSTEM.md](../../harness_packaging/DISTRIBUTION_SYSTEM.md).
