"""Export extracted Bilibili data to Excel or CSV.

[INPUT]
- session: BrowserSession
- args: {"data": str, "filename": str?, "format": "xlsx" | "csv"?}

[OUTPUT]
- JSON summary containing filepath, row_count, file_size_bytes, etc.

[POS]
Bilibili domain skill executable tool.
"""

from __future__ import annotations

import json
from typing import Any

from myrm_agent_harness.toolkits.browser.domain_skills.social_export import export_records


async def export_data(session: Any, args: dict[str, Any]) -> str:
    """Export records to spreadsheet file."""
    raw_data = args.get("data", "[]")
    filename = args.get("filename")
    fmt = args.get("format", "xlsx")

    summary = export_records(
        records=raw_data,
        filename=filename,
        export_format=str(fmt),
    )
    return json.dumps(summary, ensure_ascii=False, indent=2)
