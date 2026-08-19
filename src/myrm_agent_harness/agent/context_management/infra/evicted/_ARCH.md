# evicted/

## Overview
UECD (Unified Evicted Content Delivery) subpackage: persist oversized tool outputs to `.context/{chat_id}/evicted/`, paginated reads, disk cap markers, and FilterProcessor overflow delegate.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Facade | Re-exports public UECD API for harness/server callers | — |
| `markers.py` | Core | Disk cap marker template + regex probe SSOT (writer/reader coupling point) | ✅ |
| `content.py` | Core | 2MB cap, `{source}_{hex8}.{ext}` naming, persist/footer, SSE `EvictedRefPayload` | ✅ |
| `reader.py` | Core | Streaming line-range + meta readers for GUI/API pagination | ✅ |
| `persister.py` | Core | FilterProcessor backup persist delegate | ✅ |

## Key Dependencies

- `core.context_vars`, `infra.atomic_write`
- Server: `app/api/files/evicted.py` imports reader + content via this facade
