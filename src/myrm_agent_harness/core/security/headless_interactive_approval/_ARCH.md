# headless_interactive_approval/

## Overview

Headless Agent Interactive Approval, Webhook Relay, and Hold-Resume Suite. src/myrm_agent_harness/core/security/headless_interactive_approval/__init__.py [INPUT] myrm_agent_harness.core.security.headless_interactive_approval.* [OUTPUT] __all__.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Headless Agent Interactive Approval, Webhook Relay, and Hold-Resume Suite — src/myrm_agent_harness/core/security/headless_interactive_approval/__init__.py [INPUT] myrm_agent_harness.core.security.headless_interactive_approval.* [OUTPUT] __all__ | ✅ |
| continuation_conduit.py | Core | Streaming reasoning continuation conduit for suspended headless execution — src/myrm_agent_harness/core/security/headless_interactive_approval/continuation_conduit.py [INPUT] myrm_agent_harness.core.security.headless_interactive_approval.types [OUTPUT] StreamingContinuationConduit | ✅ |
| hold_state_machine.py | Core | Atomic Hold-Resume state machine for headless agent interactive approval — src/myrm_agent_harness/core/security/headless_interactive_approval/hold_state_machine.py [INPUT] asyncio, time, uuid, myrm_agent_harness.core.security.headless_interactive_approval.types [OUTPUT] HeadlessHoldStateMachine | ✅ |
| types.py | Core | Type definitions for Headless Agent Interactive Approval, Webhook Relay, and Hold-Resume Conduit — src/myrm_agent_harness/core/security/headless_interactive_approval/types.py [INPUT] enum, dataclasses [OUTPUT] ApprovalHoldStatus, RiskActionDescriptor, ApprovalHoldTicket, WebhookRelayPayload, StreamHoldChunk | ✅ |
| webhook_relay.py | Core | Interactive approval webhook relay for multi-channel external notifications — src/myrm_agent_harness/core/security/headless_interactive_approval/webhook_relay.py [INPUT] myrm_agent_harness.core.security.headless_interactive_approval.types [OUTPUT] InteractiveApprovalWebhookRelay | ✅ |
