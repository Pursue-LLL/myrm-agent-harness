# spaces/

## Overview
Browser task spaces module. Manages isolated execution spaces (`BrowserTaskSpace`) each binding a dedicated BrowserContext, BrowserSession, and an asyncio mutex lock, orchestrated by `HarnessTaskSpaceManager` under quota and idle-eviction constraints.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Browser task spaces module public entry point. Exports BrowserTaskSpace and HarnessTaskSpaceManager. | ✅ |
| `task_space.py` | Core | Isolated browser execution workspace entity with exclusive context and concurrency lock. | ✅ |
| `space_manager.py` | Core | Manager for parallel browser task spaces with quota enforcement and idle pruning. | ✅ |

## Key Dependencies

- `patchright.async_api.BrowserContext`
- `myrm_agent_harness.toolkits.browser.session.browser_session.BrowserSession`

