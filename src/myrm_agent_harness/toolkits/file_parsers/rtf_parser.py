"""RTF file parser.

[INPUT]
- file path: RTF 文件
- myrm_agent_harness.toolkits.file_parsers.base::FileParser (POS: 解析器基类)

[OUTPUT]
- RtfParser.parse: RTF → 纯文本（控制词剥离，best-effort）
- RtfParser.supported_extensions: [".rtf"]

[POS]
RTF parsing layer that strips control words/groups to produce plain text for
downstream ingestion.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from myrm_agent_harness.toolkits.file_parsers.base import FileParser

logger = logging.getLogger(__name__)

_RTF_CONTROL = re.compile(r"\\(?!par\b)[a-zA-Z]+\d* ?")
_RTF_GROUP = re.compile(r"[{}]")
_RTF_PAR = re.compile(r"\\par\b ?")


class RtfParser(FileParser):
    """Parse RTF into plain text (control-word strip, best-effort)."""

    async def parse(self, file_path: str) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        raw = path.read_text(encoding="utf-8", errors="ignore")
        text = _RTF_PAR.sub("\n", raw)
        text = _RTF_CONTROL.sub("", text)
        text = _RTF_GROUP.sub("", text)
        cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        logger.info("RTF parsed: %s, length=%d", path.name, len(cleaned))
        return cleaned

    @property
    def supported_extensions(self) -> list[str]:
        return [".rtf"]
