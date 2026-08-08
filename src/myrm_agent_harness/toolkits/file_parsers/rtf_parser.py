"""RTF file parser."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from myrm_agent_harness.toolkits.file_parsers.base import FileParser

logger = logging.getLogger(__name__)

_RTF_CONTROL = re.compile(r"\\[a-zA-Z]+\d* ?")
_RTF_GROUP = re.compile(r"[{}]")


class RtfParser(FileParser):
    """Parse RTF into plain text (control-word strip, best-effort)."""

    async def parse(self, file_path: str) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        raw = path.read_text(encoding="utf-8", errors="ignore")
        text = _RTF_CONTROL.sub("", raw)
        text = _RTF_GROUP.sub("", text)
        text = text.replace("\\'", "").replace("\\par", "\n")
        cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        logger.warning("RTF parsed: %s, length=%d", path.name, len(cleaned))
        return cleaned

    @property
    def supported_extensions(self) -> list[str]:
        return [".rtf"]
