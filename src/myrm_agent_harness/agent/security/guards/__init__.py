"""Security guards for the Agent runtime.

Available guards:
- loop_guard: Detects logical loops (repetition, ping-pong, no-progress, divergence)
- frequency_guard: Detects time-based call frequency anomalies (DoS prevention)
- taint_tracker: Tracks information flow labels (prompt→command injection prevention)
- estop: Global emergency stop mechanism
- context_budget: Context window size management
- privacy_tracker: PII and privacy tracking
- ssrf_guard: SSRF protection for network tools

[POS]
Session-level security guards integrated into tool_interceptor_middleware.
Each guard is an independent module; the middleware orchestrates execution order.
"""
