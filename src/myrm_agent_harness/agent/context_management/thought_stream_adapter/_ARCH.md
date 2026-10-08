# thought_stream_adapter

Architecture and module inventory for the `thought_stream_adapter` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting agent thought normalizer, client negotiator, heartbeat conduit, and facade suite |
| `thought_adapter_types.py` | Domain models and contracts for agent thought streaming and dual-mode external client adapter |
| `agent_thought_normalizer.py` | Agent thought and action normalizer transforming internal cognition and execution into formatted representations |
| `client_capability_negotiator.py` | Client capability negotiator for adaptive determination of reasoning streaming mode |
| `long_reasoning_heartbeat_conduit.py` | Keep-alive heartbeat conduit for preventing gateway timeouts during long reasoning or tool execution |
| `agent_thought_stream_adapter_suite.py` | Comprehensive facade suite for agent thought streaming and dual-mode external client bridging |
