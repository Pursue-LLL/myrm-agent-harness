# server/

## Overview
ACP Server — bridges IDE clients to the agent system via ACP protocol.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | ACP Server — bridges IDE clients to the agent system via ACP protocol. | — |
| bridge.py | Core | ACP Session lifecycle management layer. Handles session-to-agent instance mapping, prompt forwarding | ✅ |
| event_translator.py | Core | AgentEvent → ACP SessionNotification translation. | ✅ |
| server.py | Core | ACP protocol layer. Implements the ACP JSON-RPC protocol spec, translating IDE client requests | ✅ |

## Key Dependencies

- `utils`
