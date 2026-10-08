# cross_harness_ast/

## Overview
Cross-Harness Context State AST, heterogeneous session roaming, and lossless rehydration subsystem. Provides framework-agnostic session intermediate representations, bilateral serialization/hydration bridges across diverse agent engines (Claude Code, Hermes, Codex, UHP Standard), persistent sandbox artifact continuity assurance, and in-stream hot-swap health gates.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Package facade exporting AST types, state engine, hydration bridge, artifact gateway, and suite. | — |
| ast_types.py | Types | Strongly typed models for session state ASTs, turns, content blocks, tool invocations, artifact references, and hot-swap status badges. | ✅ |
| state_ast_engine.py | Core | AST creation, manipulation, token estimation, and integrity validation engine. | ✅ |
| heterogeneous_hydration_bridge.py | Core | Bilateral converter serializing canonical ASTs into alien harness formats and rehydrating external payloads into ASTs. | ✅ |
| artifact_continuity_gateway.py | Core | Sandbox artifact verification gateway preserving cryptographic digest continuity and file existence across harness switches. | ✅ |
| cross_harness_suite.py | Facade | Unified facade suite orchestrating serialization, hydration, hot-swap readiness assessment, and artifact attachment. | ✅ |

## Key Dependencies

- stdlib: `time`, `hashlib`, `uuid`, `json`, `pathlib`, `dataclasses`, `enum`, `typing`
- Internal: `myrm_agent_harness.agent.context_management`
