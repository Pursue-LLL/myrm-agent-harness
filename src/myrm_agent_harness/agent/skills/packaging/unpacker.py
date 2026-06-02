"""技能包解析

将技能 ZIP 解析为文件字典和元数据。

[INPUT]
- (none)

[OUTPUT]
- UnpackResult: class — Unpack Result
- SkillUnpacker: class — Skill Unpacker

[POS]
Provides UnpackResult, SkillUnpacker.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from myrm_agent_harness.backends.skills.scanning import safe_extract_zip

from .validator import SkillPackageInfo, is_forbidden_file, validate_skill_zip

logger = logging.getLogger(__name__)


@dataclass
class UnpackResult:
    """解包结果"""

    success: bool
    skill_info: SkillPackageInfo | None
    files: dict[str, bytes] | None
    error: str | None = None


class SkillUnpacker:
    """技能解包器"""

    def unpack(self, zip_content: bytes) -> UnpackResult:
        """解析并提取 ZIP 内容"""
        try:
            info = validate_skill_zip(zip_content)
            if not info.is_valid:
                return UnpackResult(
                    success=False,
                    skill_info=None,
                    files=None,
                    error="; ".join(info.validation_errors),
                )

            file_contents = safe_extract_zip(zip_content, forbidden_check=is_forbidden_file)

            return UnpackResult(
                success=True,
                skill_info=info,
                files=file_contents,
            )

        except Exception as e:
            logger.error(f"Skill unpack failed: {e}")
            return UnpackResult(
                success=False,
                skill_info=None,
                files=None,
                error=str(e),
            )
