# rate_limit/

## Overview
Proactive rate limit tracking capabilities.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Exports RateLimitBucket, RateLimitState, parse_rate_limit_headers, RateLimitTracker | ✅ |
| parser.py | Core | Parser for extracting rate limit info from LLM provider HTTP headers. | ✅ |
| tracker.py | Core | In-memory tracker for LLM provider rate limits. | ✅ |
| types.py | Core | Data structures for proactive rate limit tracking. | ✅ |
