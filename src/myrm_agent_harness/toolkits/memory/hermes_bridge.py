"""Hermes and OpenViking zero-friction memory migration parser and bridge.

[INPUT]
- Raw markdown / JSON from Hermes or OpenViking export formats
- toolkits.memory.types::BaseMemory, SemanticMemory, ProceduralMemory, EpisodicMemory
- toolkits.memory.domain_types::MemoryDomain, DomainCategory, infer_domain_and_category

[OUTPUT]
- parse_hermes_markdown: Parse single or multi-doc Markdown into BaseMemory entities.
- parse_hermes_json: Parse exported JSON format into BaseMemory entities.
- import_hermes_bundle: Ingest parsed memories into MemoryManager with L0/L1/L2 fidelity.

[POS]
Zero-friction migration bridge supporting OpenViking L0/L1/L2 progressive memory
structures and Hermes export formats.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.domain_types import (
    DomainCategory,
    MemoryDomain,
    infer_domain_and_category,
)
from myrm_agent_harness.toolkits.memory.types import (
    BaseMemory,
    EpisodicMemory,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_L1_SECTION_RE = re.compile(
    r"(?:^|\n)##\s*(?:Overview|Summary|L1 Overview)\s*\n(.*?)(?=\n##|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _parse_simple_yaml_frontmatter(yaml_text: str) -> dict[str, str]:
    """Lightweight zero-dependency key-value frontmatter parser."""
    meta: dict[str, str] = {}
    for line in yaml_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            meta[key.strip().lower()] = val.strip().strip("'\"")
    return meta


def _extract_l0_l1_l2(raw_content: str, meta: dict[str, str]) -> tuple[str, str, str]:
    """Extract L0 (punchy summary), L1 (overview), and L2 (full verbatim)."""
    # L0
    l0 = meta.get("l0") or meta.get("summary_l0") or meta.get("summary") or ""
    if not l0:
        first_line = raw_content.strip().splitlines()[0] if raw_content.strip() else ""
        first_line = re.sub(r"^#+\s*", "", first_line).strip()
        l0 = first_line[:120].strip()

    # L1
    l1 = meta.get("l1") or meta.get("overview_l1") or meta.get("overview") or ""
    if not l1:
        match = _L1_SECTION_RE.search(raw_content)
        if match:
            l1 = match.group(1).strip()
        else:
            # Fallback to first non-heading paragraph
            paragraphs = [p.strip() for p in raw_content.split("\n\n") if p.strip()]
            for p in paragraphs:
                if not p.startswith("#"):
                    l1 = p[:400].strip()
                    break

    # L2 is the full verbatim content
    l2 = raw_content.strip()
    return l0, l1, l2


def parse_hermes_markdown(content: str) -> list[BaseMemory]:
    """Parse Hermes / OpenViking markdown document into typed memory objects."""
    if not content.strip():
        return []

    # Check for multi-doc markdown separated by --- markers
    raw_blocks = re.split(r"\n===\s*\n|\n---\s*---\s*\n", content)
    results: list[BaseMemory] = []

    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue

        meta: dict[str, str] = {}
        body = block
        fm_match = _FRONTMATTER_RE.match(block)
        if fm_match:
            meta = _parse_simple_yaml_frontmatter(fm_match.group(1))
            body = fm_match.group(2).strip()

        l0, l1, l2 = _extract_l0_l1_l2(body, meta)
        mem_id = meta.get("id") or f"hermes-{uuid.uuid4().hex[:12]}"

        # Domain & Category inference
        raw_dom = meta.get("domain", "").lower()
        domain: MemoryDomain | None = None
        for d in MemoryDomain:
            if d.value == raw_dom:
                domain = d
                break

        raw_cat = meta.get("category") or meta.get("domain_category", "")
        mem_type_str = meta.get("type", "semantic").lower()

        if domain is None or not raw_cat:
            inferred_dom, inferred_cat = infer_domain_and_category(
                mem_type_str,
                content=l2,
            )
            if domain is None:
                domain = inferred_dom
            if not raw_cat:
                raw_cat = inferred_cat.value

        if mem_type_str == "procedural":
            trigger = meta.get("trigger") or l0
            action = meta.get("action") or l1 or l2
            mem = ProceduralMemory(
                id=mem_id,
                trigger=trigger,
                action=action,
                summary_l0=l0,
                overview_l1=l1,
                domain=domain,
                domain_category=raw_cat,
            )
        elif mem_type_str == "episodic":
            event_type = meta.get("event_type", "observation")
            mem = EpisodicMemory(
                id=mem_id,
                event_type=event_type,
                content=l2,
                summary_l0=l0,
                overview_l1=l1,
                domain=domain,
                domain_category=raw_cat,
            )
        else:
            mem = SemanticMemory(
                id=mem_id,
                content=l2,
                summary_l0=l0,
                overview_l1=l1,
                domain=domain,
                domain_category=raw_cat,
            )
        results.append(mem)

    return results


def parse_hermes_json(raw_json: str | list[object] | dict[str, object]) -> list[BaseMemory]:
    """Parse Hermes / OpenViking JSON export into typed memory objects."""
    if isinstance(raw_json, str):
        parsed = json.loads(raw_json)
    else:
        parsed = raw_json

    items: list[dict[str, object]] = []
    if isinstance(parsed, list):
        for it in parsed:
            if isinstance(it, dict):
                items.append({str(k): v for k, v in it.items()})
    elif isinstance(parsed, dict):
        if "memories" in parsed and isinstance(parsed["memories"], list):
            for it in parsed["memories"]:
                if isinstance(it, dict):
                    items.append({str(k): v for k, v in it.items()})
        else:
            for val in parsed.values():
                if isinstance(val, list):
                    for it in val:
                        if isinstance(it, dict):
                            items.append({str(k): v for k, v in it.items()})

    memories: list[BaseMemory] = []
    for d in items:
        mem_id = str(d.get("id") or f"hermes-{uuid.uuid4().hex[:12]}")
        content = str(d.get("content") or d.get("text") or "")
        summary_l0 = str(d.get("summary_l0") or d.get("summary") or content[:120].strip())
        overview_l1 = str(d.get("overview_l1") or d.get("overview") or content[:400].strip())
        mem_type = str(d.get("type") or d.get("memory_type") or "semantic").lower()

        # Domain
        domain_str = str(d.get("domain", "")).lower()
        domain = MemoryDomain.USER
        for dm in MemoryDomain:
            if dm.value == domain_str:
                domain = dm
                break

        domain_cat = str(d.get("domain_category") or d.get("category") or "")
        if not domain_cat or domain_str == "":
            inf_dom, inf_cat = infer_domain_and_category(mem_type, content=content)
            if domain_str == "":
                domain = inf_dom
            if not domain_cat:
                domain_cat = inf_cat.value

        if mem_type == "procedural":
            trigger = str(d.get("trigger") or summary_l0)
            action = str(d.get("action") or overview_l1 or content)
            mem = ProceduralMemory(
                id=mem_id,
                trigger=trigger,
                action=action,
                summary_l0=summary_l0,
                overview_l1=overview_l1,
                domain=domain,
                domain_category=domain_cat,
            )
        elif mem_type == "episodic":
            event_type = str(d.get("event_type", "observation"))
            mem = EpisodicMemory(
                id=mem_id,
                event_type=event_type,
                content=content,
                summary_l0=summary_l0,
                overview_l1=overview_l1,
                domain=domain,
                domain_category=domain_cat,
            )
        else:
            mem = SemanticMemory(
                id=mem_id,
                content=content,
                summary_l0=summary_l0,
                overview_l1=overview_l1,
                domain=domain,
                domain_category=domain_cat,
            )
        memories.append(mem)

    return memories


async def import_hermes_bundle(
    manager: MemoryManager,
    bundle_content: str,
    *,
    is_json: bool = False,
) -> tuple[int, int]:
    """Parse and import Hermes/OpenViking payload into MemoryManager.

    Returns:
        (success_count, fail_count)
    """
    try:
        if is_json:
            parsed = parse_hermes_json(bundle_content)
        else:
            # Auto-detect JSON if starting with [ or {
            stripped = bundle_content.strip()
            if stripped.startswith(("{", "[")):
                parsed = parse_hermes_json(stripped)
            else:
                parsed = parse_hermes_markdown(bundle_content)
    except Exception as e:
        logger.error("Failed to parse Hermes bundle: %s", e)
        return 0, 1

    success = 0
    failures = 0
    for mem in parsed:
        try:
            await manager.save_memory(mem)
            success += 1
        except Exception as e:
            logger.warning("Failed to ingest imported memory %s: %s", mem.id, e)
            failures += 1

    return success, failures
