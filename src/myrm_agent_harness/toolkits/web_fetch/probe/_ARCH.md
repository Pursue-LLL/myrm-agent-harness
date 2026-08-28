# probe/

## Overview
Network probes and charset detection for web fetch decoding.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports HTTP/3 probe helpers | ✅ |
| http3_probe.py | Util | HTTP/3 protocol probe and retry metrics | ✅ |
| charset_detector.py | Util | Multi-tier charset detection | ✅ |

## Dependencies

- `httpx`, optional chardet
