"""Extract structured video entries from Douyin via browser session.

Executed inside the browser_execute_script sandbox via ``run_site_tool``.
Receives ``session`` (BrowserSession) and ``args`` dict as runtime parameters.

[INPUT]
- session: Active BrowserSession instance with tab and snapshot support
- args: Optional dictionary containing:
    - max_items: Maximum videos to collect (default: 10)
    - export_format: "json" or "csv" (default: "json")

[OUTPUT]
- String containing structured JSON or CSV data

[POS]
Self-contained domain tool for Douyin video harvesting.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.session import BrowserSession


def _check_douyin_traps(text: str) -> dict[str, str] | None:
    """Detect known Douyin login walls or slider CAPTCHA prompts."""
    login_patterns = [
        r"登录后查看更多",
        r"扫码登录",
        r"密码登录",
        r"滑动滑块完成验证",
        r"请完成安全验证",
        r"验证码登录",
    ]
    for pattern in login_patterns:
        if re.search(pattern, text):
            return {
                "status": "login_required",
                "message": f"Douyin login wall or verification detected: '{pattern}'. Use browser_ask_human_tool for user login.",
            }
    return None


def _format_douyin_csv(items: list[dict[str, str]]) -> str:
    """Format items as Excel-friendly CSV with UTF-8 BOM."""
    if not items:
        return "\ufeffvideo_id,title,author,likes,url\n"

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM
    fieldnames = ["video_id", "title", "author", "likes", "url"]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    for item in items:
        cleaned_item = {k: str(item.get(k, "")).replace("\r", " ").replace("\n", " ").strip() for k in fieldnames}
        writer.writerow(cleaned_item)
    return output.getvalue()


async def get_video_feed(session: BrowserSession, args: dict[str, str | int]) -> str:
    """Extract video cards from current Douyin feed, search results, or user profile.

    Args:
        session: Active BrowserSession.
        args: Arguments dict containing max_items and export_format.

    Returns:
        JSON string or CSV string containing video items.
    """
    max_items = int(args.get("max_items", 10))
    export_format = str(args.get("export_format", "json")).lower().strip()

    refs = session.get_all_refs()
    if not refs:
        await session.snapshot()
        refs = session.get_all_refs()

    items: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    video_id_regex = re.compile(r"(?:/video/|aweme_id=)?(\d{18,20})")

    # Step 1: Scan ARIA refs
    for ref_id, info in refs.items():
        if len(items) >= max_items:
            break

        name = (info.name or "").strip()
        if not name:
            continue

        id_match = video_id_regex.search(name)
        video_id = id_match.group(1) if id_match else f"douyin_{ref_id}"

        # Likes extraction (e.g. 12.3w / 4567赞)
        like_match = re.search(r"(\d+(?:\.\d+)?[wW万]?\s*(?:赞|like)?)", name)
        likes = like_match.group(1) if like_match else ""

        # Author extraction if @author is in name
        author_match = re.search(r"@([^\s]+)", name)
        author = author_match.group(1) if author_match else ""

        if video_id not in seen_ids and len(name) > 6:
            seen_ids.add(video_id)
            title = name.split("\n")[0].strip()[:150]
            items.append(
                {
                    "video_id": video_id,
                    "title": title,
                    "author": author,
                    "likes": likes,
                    "url": f"https://www.douyin.com/video/{video_id}" if not video_id.startswith("douyin_") else "",
                }
            )

    # Step 2: Fallback to page text extraction
    if len(items) < max_items:
        page_text = await session.extract_text(max_length=50000)

        if not items:
            trap = _check_douyin_traps(page_text)
            if trap is not None:
                return json.dumps(trap, ensure_ascii=False, indent=2)

        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        for i, line in enumerate(lines):
            if len(items) >= max_items:
                break
            match = video_id_regex.search(line)
            if match:
                vid = match.group(1)
                if vid not in seen_ids:
                    seen_ids.add(vid)
                    candidate_title = lines[i - 1] if i > 0 and len(lines[i - 1]) > 5 else line
                    items.append(
                        {
                            "video_id": vid,
                            "title": candidate_title[:150],
                            "author": "",
                            "likes": "",
                            "url": f"https://www.douyin.com/video/{vid}",
                        }
                    )

    if export_format == "csv":
        return _format_douyin_csv(items)

    return json.dumps(items, ensure_ascii=False, indent=2)
