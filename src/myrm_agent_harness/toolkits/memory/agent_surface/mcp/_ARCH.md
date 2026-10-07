# mcp/

## Overview
Cross-tool memory MCP interop gateway & wire adapter (ai-memory parity).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public entry point for ai-memory wire interoperability and MCP server gateway. | ✅ |
| `ai_memory_wire_adapter.py` | Core | Wire-format adapter emulating the 5.3k Star ai-memory MCP tool protocol. | ✅ |
| `server_factory.py` | Core | Server factory creating standard MCP server with ai-memory wire parity. | ✅ |
| `types.py` | Types | Data models for ai-memory wire format interoperability and cross-tool MCP gateway. | ✅ |

## Key Dependencies

- `agent.context_management.handoff`
- `toolkits.memory.privacy_gate`
- External libraries: `mcp`, `pydantic`
