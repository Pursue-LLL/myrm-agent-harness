# cross_agent/

## Overview

Cross-agent composable context isolation, divergence arbitration probe, and handoff integrity suite. Core module for multi-agent shared memory, context composition, and divergence settlement.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Cross-agent composable context isolation, divergence arbitration probe, and handoff integrity suite — Core module for multi-agent shared memory, context composition, and divergence settlement. | ✅ |
| arbitrator.py | Core | Multi-agent memory divergence detection and ground truth arbitration probe — Core arbitration probe that prevents logic divergence and task fractures when two agents remember the same task differently. Strict typing applied: No `Any` types allowed. | ✅ |
| integrity.py | Core | Handoff integrity sealing and signature verification pipeline for cross-agent task transfer — Integrity verification pipeline preventing cross-agent context tampering, hallucination propagation, and stale state injection. Strict typing applied: No `Any` types allowed. | ✅ |
| projector.py | Core | Four-layer composable context projection engine for multi-agent coordination — Orchestrates virtual reference layer composition, strict private scratchpad isolation, and KV-cache optimization. Strict typing applied: No `Any` types allowed. | ✅ |
| tool.py | Core | Agent-facing LangChain tool for cross-agent memory divergence detection and ground truth arbitration — Agent-facing LangChain tool allowing collaborating agents to arbitrate memory conflicts using ground truth, coordinator authority, and confidence weighting. Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | Type definitions for cross-agent composable context and memory conflict arbitration — Core contracts for multi-agent shared memory, context composition, and divergence settlement. Strict typing applied: No `Any` types allowed. | ✅ |
