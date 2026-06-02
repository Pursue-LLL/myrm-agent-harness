"""Skill discovery helper functions.

Shared utilities for scanning, deduplication, ranking, origin tracking, and LobeHub conversion.

[INPUT]
- backends.skills.discovery_protocols::SkillSearchResult (POS: SkillBackend SkillBackend SkillDiscoveryBackend)
- backends.skills.scanning::ScanResult (POS: Scan result cache layer. Stores scan results in Volume (~/.myrm/skill_scans/) to avoid redundant scanning. Critical for performance: 20x speedup for repeat scans. Cache key: SHA256 hash of skill content Cache location: ~/.myrm/skill_scans/{content_hash}.json Expiration: 60 days TTL (auto-cleanup on get))

[OUTPUT]
- scan_all_text_files: Scan all text files in a skill package for security threats.
- deduplicate: Deduplicate by name, keeping first occurrence (higher pri...
- rank_results: Rank by source priority + stars + keyword match.
- fetch_lobehub_as_skill: Download a LobeHub agent JSON and convert it to a SKILL.m...
- write_origin: Write origin.json to skill directory for update tracking.

[POS]
Skill discovery helper functions.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx

from myrm_agent_harness.backends.skills.discovery_protocols import SkillSearchResult
from myrm_agent_harness.backends.skills.scanning import ScanResult, scan_skill_content

logger = logging.getLogger(__name__)

_SCANNABLE_EXTENSIONS = frozenset(
    {".md", ".py", ".sh", ".js", ".ts", ".yaml", ".yml", ".json", ".txt", ".toml", ".cfg", ".ini", ".html"}
)

SOURCE_PRIORITY = {"prebuilt": 100, "clawhub": 60, "skills_sh": 50, "github": 30, "lobehub": 20}


def scan_all_text_files(skill_name: str, files: dict[str, bytes]) -> ScanResult:
    """Scan all text files in a skill package for security threats.

    Merges findings from every scannable file into a single ScanResult.
    Binary files are skipped.
    """
    merged = ScanResult(skill_name=skill_name)

    for rel_path, content in files.items():
        suffix = Path(rel_path).suffix.lower()
        if suffix not in _SCANNABLE_EXTENSIONS:
            continue

        try:
            text = content.decode("utf-8", errors="replace")
        except Exception:
            continue

        file_result = scan_skill_content(f"{skill_name}/{rel_path}", text)
        merged.findings.extend(file_result.findings)

    return merged


def deduplicate(results: list[SkillSearchResult]) -> list[SkillSearchResult]:
    """Deduplicate by name, keeping first occurrence (higher priority sources first)."""
    seen: set[str] = set()
    deduped: list[SkillSearchResult] = []
    for r in results:
        key = r.name.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped


def rank_results(results: list[SkillSearchResult], query: str) -> list[SkillSearchResult]:
    """Rank by source priority + stars + keyword match."""
    keywords = query.lower().split()

    def score(r: SkillSearchResult) -> float:
        s = SOURCE_PRIORITY.get(r.source, 0)
        s += min(r.stars, 500) * 0.1
        name_lower = r.name.lower()
        desc_lower = r.description.lower()
        for kw in keywords:
            if kw in name_lower:
                s += 20
            if kw in desc_lower:
                s += 5
        return s

    return sorted(results, key=score, reverse=True)


async def fetch_lobehub_as_skill(detail: SkillSearchResult) -> dict[str, bytes]:
    """Download a LobeHub agent JSON and convert it to a SKILL.md file set."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(detail.install_url)
        if resp.status_code != 200:
            raise ValueError(f"LobeHub agent fetch failed: HTTP {resp.status_code}")
        data = resp.json()

    if not isinstance(data, dict):
        raise ValueError("LobeHub agent data is not a valid JSON object")

    meta = data.get("meta", data)
    if not isinstance(meta, dict):
        meta = data

    title = str(meta.get("title", detail.name))
    description = str(meta.get("description", detail.description))
    system_role = str(data.get("config", {}).get("systemRole", ""))

    tags_raw = meta.get("tags", [])
    tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else []
    tag_line = ", ".join(tags) if tags else ""

    skill_md_lines = [
        "---",
        f"name: {title}",
        f"description: {description[:500]}",
        f"tags: [{tag_line}]",
        "source: lobehub",
        "---",
        "",
        f"# {title}",
        "",
        description,
        "",
    ]
    if system_role:
        skill_md_lines.extend(["## System Prompt", "", system_role, ""])

    skill_md = "\n".join(skill_md_lines)
    return {"SKILL.md": skill_md.encode("utf-8")}


ORIGIN_FILENAME = "origin.json"


def write_origin(skill_dir: Path, *, source: str, skill_id: str) -> None:
    """Write origin.json to skill directory for update tracking."""
    origin = {
        "source": source,
        "skill_id": skill_id,
        "installed_at": datetime.now(UTC).isoformat(),
    }
    try:
        (skill_dir / ORIGIN_FILENAME).write_text(json.dumps(origin), encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to write origin.json: %s", e)


def read_origin(skill_dir: Path) -> dict[str, str]:
    """Read origin.json from a skill directory. Returns empty dict if missing."""
    origin_file = skill_dir / ORIGIN_FILENAME
    if not origin_file.exists():
        return {}
    try:
        return json.loads(origin_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
