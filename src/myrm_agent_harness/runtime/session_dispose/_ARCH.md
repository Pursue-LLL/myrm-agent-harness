# session_dispose/

## Overview
Agent session dispose pending requests purge and delivery ACK suite.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Agent session dispose pending requests purge and delivery ACK suite. | — |
| `delivery_ack_coordinator.py` | Core | Delivery acknowledgement (ACK) coordinator for inter-agent communication. | ✅ |
| `dispose_ack_types.py` | Core | Strongly typed data contracts for session dispose hard-purge and delivery acknowledgement. | ✅ |
| `session_dispose_purger.py` | Core | Session in-flight request hard-purge manager on disposal. | ✅ |
