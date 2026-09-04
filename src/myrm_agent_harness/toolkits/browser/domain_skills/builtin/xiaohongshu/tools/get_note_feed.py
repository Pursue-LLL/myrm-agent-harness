"""Extract structured note entries from Xiaohongshu (RED) via browser session.

Executed inside the browser_execute_script sandbox via ``run_site_tool``.
Receives ``session`` (BrowserSession) and ``args`` dict as runtime parameters.

[INPUT]
- session: Active BrowserSession instance with tab and snapshot support
- args: Optional dictionary containing:
    - max_items: Maximum notes to collect (default: 10)
    - export_format: "json" or "csv" (default: "json")

[OUTPUT]
- String containing structured JSON or CSV data

[POS]
Self-contained domain tool for Xiaohongshu note harvesting.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.session import BrowserSession


def _check_xhs_traps(text: str) -> dict[str, str] | None:
    """Detect known Xiaohongshu login walls or verification prompts."""
    login_patterns = [
        r"登录后查看更多优质内容",
        r"请登录",
        r"登录探索更多",
        r"扫码登录",
        r"短信验证码登录",
        r"完成拼图验证",
        r"安全验证",
    ]
    for pattern in login_patterns:
        if re.search(pattern, text):
            return {
                "status": "login_required",
                "message": f"Xiaohongshu login wall or verification detected: '{pattern}'. Use browser_ask_human_tool for user login.",
            }
    return None


def _format_xhs_csv(items: list[dict[str, str]]) -> str:
    """Format items as Excel-friendly CSV with UTF-8 BOM."""
    if not items:
        return "\ufeffnote_id,title,author,likes,note_type,url\n"

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM
    fieldnames = ["note_id", "title", "author", "likes", "note_type", "url"]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    for item in items:
        cleaned_item = {k: str(item.get(k, "")).replace("\r", " ").replace("\n", " ").strip() for k in fieldnames}
        writer.writerow(cleaned_item)
    return output.getvalue()


async def get_note_feed(session: BrowserSession, args: dict[str, str | int]) -> str:
    """Extract note cards from current Xiaohongshu feed, explore, or search results.

    Args:
        session: Active BrowserSession.
        args: Arguments dict containing max_items and export_format.

    Returns:
        JSON string or CSV string containing note items.
    """
    max_items = int(args.get("max_items", 10))
    export_format = str(args.get("export_format", "json")).lower().strip()

    refs = session.get_all_refs()
    if not refs:
        await session.snapshot()
        refs = session.get_all_refs()

    items: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    # Regex for 24-character hexadecimal note ID in Xiaohongshu URLs
    note_id_pattern = re.compile(r"([0-9a-f]{24})")

    # Step 1: Scan ARIA refs
    for ref_id, info in refs.items():
        if len(items) >= max_items:
            break

        name = (info.name or "").strip()
        if not name:
            continue

        id_match = note_id_pattern.search(name)
        note_id = id_match.group(1) if id_match else f"xhs_ref_{ref_id}"

        # Likes extraction
        like_match = re.search(r"(\d+(?:\.\d+)?[万kK]?\s*(?:赞|like|Likes)?)", name, re.IGNORECASE)
        likes = like_match.group(1) if like_match else ""

        # Note type estimation
        note_type = "video" if ("视频" in name or "▶" in name) else "image"

        if note_id not in seen_ids and len(name) > 6:
            seen_ids.add(note_id)
            title = name.split("\n")[0].strip()[:150]
            items.append(
                {
                    "note_id": note_id,
                    "title": title,
                    "author": "",
                    "likes": likes,
                    "note_type": note_type,
                    "url": f"https://www.xiaohongshu.com/explore/{note_id}" if not note_id.startswith("xhs_ref_") else "",
                }
            )

    # Step 2: Fallback to page text extraction if needed
    if len(items) < max_items:
        page_text = await session.extract_text(max_length=50000)

        if not items:
            trap = _check_xhs_traps(page_text)
            if trap is not None:
                return json.dumps(trap, ensure_ascii=False, indent=2)

        blocks = page_text.split("\n\n")
        for block in blocks:
            if len(items) >= max_items:
                break
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue

            first_line = lines[0]
            if len(first_line) > 5 and not any(kw in first_line for kw in ["登录", "推荐", "发现", "发布"]):
                synthetic_id = f"note_{len(items) + 1}"
                if synthetic_id not in seen_ids:
                    seen_ids.add(synthetic_id)
                    author = lines[1] if len(lines) > 1 and len(lines[1]) < 30 else ""
                    items.append(
                        {
                            "note_id": synthetic_id,
                            "title": first_line[:150],
                            "author": author,
                            "likes": "",
                            "note_type": "image",
                            "url": "",
                        }
                    )

    if export_format == "csv":
        return _format_xhs_csv(items)

    return json.dumps(items, ensure_ascii=False, indent=2)
