"""Artifact 数据模型和推断别名

ArtifactInfo: 工件元数据结构，用于 API 响应。
infer_language / infer_artifact_type: 简短别名，实际实现在 constants.py（SSoT）。

[INPUT]
- (none)

[OUTPUT]
- ArtifactInfo: class — Artifact Info
- infer_language: function — infer_language
- infer_artifact_type: function — infer_artifact_type

[POS]
Provides ArtifactInfo, infer_language, infer_artifact_type.
"""

from dataclasses import asdict, dataclass

from .constants import ArtifactType, infer_artifact_type_from_extension, infer_language_from_extension


@dataclass
class ArtifactInfo:
    """工件元数据，用于 API 响应和前端展示。"""

    id: str
    filename: str
    type: ArtifactType
    content_type: str
    size: int
    preview_url: str
    download_url: str
    language: str | None = None
    created_at: str | None = None
    file_path: str | None = None

    def to_dict(self) -> dict[str, str | int | None]:
        """转换为字典，ArtifactType 序列化为 str。"""
        d = asdict(self)
        d["type"] = self.type.value
        if d.get("file_path") is None:
            d.pop("file_path", None)
        return d


def infer_language(filename: str) -> str | None:
    """根据文件扩展名推断编程语言（别名）。"""
    return infer_language_from_extension(filename)


def infer_artifact_type(filename: str) -> ArtifactType:
    """根据文件扩展名推断工件类型（别名）。"""
    return infer_artifact_type_from_extension(filename)
