"""Programmatic Tool Calling (PTC) subsystem.

[INPUT]
- .models (POS: PTC data models)
- .rpc_server (POS: Asyncio RPC server)
- .dispatcher (POS: Tool call dispatcher)
- .stub_generator (POS: Dynamic stub module generation)
- .security (POS: Child process security constraints)
- .helpers (POS: Built-in helper function source)
- .ptc_injection (POS: PTC injection orchestrator for bash Python execution)

[OUTPUT]
- PtcConfig, PtcExecutionTrace, PtcRpcRequest, PtcRpcResponse
- PtcRpcServer
- PtcDispatcher
- generate_stubs
- scrub_child_env
- inject_ptc_for_python_execution

[POS]
Programmatic Tool Calling (PTC) subsystem — **DW PTC** branch infrastructure.
``inject_ptc_for_python_execution`` enables LLM-generated Python scripts to invoke
agent tools via RPC without consuming LLM context window for intermediate
results. **MCP PTC** uses bash + ``skills.*`` / ``tools.*`` IPC instead; see
EXECUTION_SYSTEM.md § PTC 家族.
"""

from myrm_agent_harness.toolkits.code_execution.ptc.dispatcher import PtcDispatcher
from myrm_agent_harness.toolkits.code_execution.ptc.models import (
    PtcConfig,
    PtcExecutionTrace,
    PtcRpcRequest,
    PtcRpcResponse,
    PtcToolCallRecord,
)
from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
    inject_ptc_for_python_execution,
)
from myrm_agent_harness.toolkits.code_execution.ptc.rpc_server import PtcRpcServer
from myrm_agent_harness.toolkits.code_execution.ptc.security import scrub_child_env
from myrm_agent_harness.toolkits.code_execution.ptc.stub_generator import (
    generate_stubs,
)

__all__ = [
    "PtcConfig",
    "PtcDispatcher",
    "PtcExecutionTrace",
    "PtcRpcRequest",
    "PtcRpcResponse",
    "PtcRpcServer",
    "PtcToolCallRecord",
    "generate_stubs",
    "inject_ptc_for_python_execution",
    "scrub_child_env",
]
