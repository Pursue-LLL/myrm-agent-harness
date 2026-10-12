# governed_write_safety/

## Overview

String-Is-Never-Authority Governed Write Safety Suite. src/myrm_agent_harness/core/security/governed_write_safety/__init__.py String-Is-Never-Authority Governed Write Safety Suite. Exports domain types, opaque registry, governed write engine, and facade. Strict typing applied: No `Any` types allowed.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | String-Is-Never-Authority Governed Write Safety Suite — src/myrm_agent_harness/core/security/governed_write_safety/__init__.py String-Is-Never-Authority Governed Write Safety Suite. Exports domain types, opaque registry, governed write engine, and facade. Strict typing applied: No `Any` types allowed. | ✅ |
| facade.py | Core | Unified facade for opaque ID abstraction, proposal governance, and atomic commit verification — src/myrm_agent_harness/core/security/governed_write_safety/facade.py [INPUT] typing, types, opaque_registry, governed_write_engine [OUTPUT] GovernedWriteSafetyFacade Unified facade for opaque ID abstraction, proposal governance, and atomic commit verification. Strict typing applied: No `Any` types allowed. | ✅ |
| governed_write_engine.py | Core | Governed write execution engine enforcing pre-image snapshots, stale rejection, and non-silent commits — src/myrm_agent_harness/core/security/governed_write_safety/governed_write_engine.py [INPUT] hashlib, time, uuid, typing, types [OUTPUT] GovernedWriteEngine Governed write execution engine enforcing pre-image snapshots, stale rejection, and non-silent commits. Strict typing applied: No `Any` types allowed. | ✅ |
| opaque_registry.py | Core | Opaque file ID registry shielding raw filesystem paths from client and model layers — src/myrm_agent_harness/core/security/governed_write_safety/opaque_registry.py [INPUT] uuid, typing [OUTPUT] OpaqueFileRegistry Opaque file ID registry shielding raw filesystem paths from client and model layers. Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | Domain types for String-Is-Never-Authority Governed Write Safety Suite — src/myrm_agent_harness/core/security/governed_write_safety/types.py [INPUT] dataclasses, enum, typing [OUTPUT] WriteProposalStatus, PreImageSnapshot, GovernedWriteProposal, ConflictRecoveryBundle, CommitWriteResult Domain types for String-Is-Never-Authority Governed Write Safety Suite. Strict typing applied: No `Any` types allowed. | ✅ |
