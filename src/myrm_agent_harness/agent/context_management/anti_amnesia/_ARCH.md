# anti_amnesia/

## Overview
Context compression silent fallback guard, window alignment, and anti-amnesia multi-tier resilience pipeline (Item 318).

Solves the critical failure mode where compression silently falls back to weak local models with small context windows, triggering catastrophic historical truncation and amnesia:
1. **Compression Model Window Capacity Asserter**: Physical assertion ensuring target model window safely fits total tokens with safety headroom ratio (1.25x), strictly forbidding silent truncation down-scaling.
2. **Chunked Map-Reduce Lossless Fallback Compactor**: When large window models are unavailable and small window fallbacks are used, slices long histories with 15% continuity overlap and hierarchically reduces intermediate findings into unified workflow memory.
3. **Compression Transparency HUD & Anti-Hanging Lock Watchdog**: 30s transaction timeout watchdog preventing zombie hanging sessions, accompanied by semantic entity fidelity assertions (>85%) and client transparency badges.
4. **Adaptive 500-Turn Budget Watchdog**: Replaces rigid 50-turn hardcodes with progressive loop fuel extension up to 500 rounds while terminating runaway idle loops after 5 consecutive stalls.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public exports for anti-amnesia context compression fallback guard and watchdog. | — |
| anti_amnesia_types.py | Models | Domain data models (`CompressionFallbackTier`, `ModelWindowSpec`, `CapacityAssertionResult`, `ChunkedSummaryNode`, `CompressionTransparencyHudState`, `TurnBudgetWatchdogState`, `AntiAmnesiaExecutionReport`). | ✅ |
| window_capacity_asserter.py | Core | Physical context window capacity evaluator and anti-truncation assertion gate (`InsufficientWindowCapacityError`, `WindowCapacityAsserter`). | ✅ |
| chunked_map_reduce_compactor.py | Core | Lossless hierarchical map-reduce compression engine with 15% overlap slicing and entity preservation (`ChunkedMapReduceCompactor`). | ✅ |
| compression_guard_and_watchdog.py | Core | 30s transaction timeout watchdog, semantic fidelity assertion, and dynamic 500-turn iteration fuel manager (`CompressionTransparencyAndLockGuard`, `AdaptiveTurnBudgetWatchdog`). | ✅ |
| anti_amnesia_suite.py | Facade | High-level developer facade orchestrating capacity assertions, fallback execution, and watchdog monitoring (`AntiAmnesiaSuite`, `ContextCompressionSilentFallbackGuardAndWindowAlignedAntiAmnesiaSuite`). | ✅ |

## Key Dependencies

- `agent.context_management` — Token estimation and message processing infrastructure
- `langchain_core.messages` — LangChain message protocols
