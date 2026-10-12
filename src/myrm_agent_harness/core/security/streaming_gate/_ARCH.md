# streaming_gate/

## Overview

Streaming Endpoint Identity Gate Parity Package.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Streaming Endpoint Identity Gate Parity Package | ✅ |
| evaluator.py | Core | Identity and scope evaluator for streaming endpoint gate parity — Harness core security engine. Enforces zero bypass on SSE and WebSocket connections, ensuring they require strict identity and resource scope parity with REST APIs. | ✅ |
| registry.py | Core | Registry for declared streaming endpoint contracts — Harness core security registry. Enforces that all SSE, WebSocket, and chunked HTTP endpoints declare an explicit security contract. | ✅ |
| types.py | Core | Domain types and models for Streaming Endpoint Identity Gate Parity — Harness core domain models ensuring streaming endpoints (SSE / WebSocket / Chunked) enforce strict identity and resource-scoped authorization parity with REST endpoints. | ✅ |
