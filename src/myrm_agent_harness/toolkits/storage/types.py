"""Storage layer type definitions


[INPUT]
- enum::Enum (POS: Python enum type)

[OUTPUT]
- FilePurpose: file purpose enum (UPLOAD, AGENT_OUTPUT, SANDBOX_ARTIFACT, etc.)
- SkillType: skill type enum (PREBUILT, LOCAL, WORKSPACE)

[POS]
Storage layer type definitions. Defines base types and enums related to storage paths (path conventions).
FilePurpose and SkillType determine the physical location of files/skills in the storage system.
As the type definition layer, depended on by both business and storage layers as single source of truth (SSOT).
"""

from __future__ import annotations

from enum import StrEnum


class FilePurpose(StrEnum):
    """FilePurpose（决定StoragePath）

    StoragePathFormat：files/{user_id}/{purpose}/{file_id}

    Attributes:
        UPLOAD: 用户Upload File（inputFile）
        GENERATED: 技能Generate File（outputFile）
        SKILL: 技能本身 File（技能包Content）
    """

    UPLOAD = "upload"
    GENERATED = "generated"
    SKILL = "skill"


class SkillType(StrEnum):
    """Skill type determines storage path: skills/{type}/{skill_id}

    Attributes:
        PREBUILT: Admin-managed built-in skills
        LOCAL: Filesystem skills scanned from user-configured paths
        WORKSPACE: Project-level skills discovered in working directory
    """

    PREBUILT = "prebuilt"
    LOCAL = "local"
    WORKSPACE = "workspace"


__all__ = [
    "FilePurpose",
    "SkillType",
]
