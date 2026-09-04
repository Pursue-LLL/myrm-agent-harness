"""Export extracted domain data to Excel or CSV.

[INPUT]
- session: BrowserSession (unused, conforms to domain tool signature)
- args: {"data": str | list, "filename": str, "format": str}

[OUTPUT]
- JSON string with export metadata (filepath, row_count, file_size_bytes)

[POS]
Domain skill export adapter tool.
"""

from __future__ import annotations

import json
from typing import Any

from myrm_agent_harness.toolkits.browser.domain_skills.social_export import export_records


async def export_data(session: Any, args: dict[str, Any]) -> str:
    """Export collected data records to Excel or CSV."""
    raw_data = args.get("data", "")
    filename = args.get("filename")
    fmt = str(args.get("format", "xlsx"))

    result = export_records(
        records=raw_data,
        filename=str(filename) if filename else None,
        export_format=fmt,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)
