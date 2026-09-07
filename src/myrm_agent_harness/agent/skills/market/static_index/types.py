"""Static skills index data models.

[INPUT]
- None (pure domain models)

[OUTPUT]
- StaticSkillItem: single skill entry in static index
- StaticIndexManifest: aggregated index metadata (version, updated_at, total_skills, etag)

[POS]
Domain models for centralized static skill index and local mirror cache.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StaticSkillItem:
    """Individual skill record in the centralized static index."""

    id: str
    name: str
    description: str
    source: str = "clawhub"
    version: str = "1.0.0"
    author: str = ""
    stars: int = 0
    downloads: int = 0
    tags: list[str] = field(default_factory=list)
    install_url: str = ""
    install_method: str = "zip"
    subdirectory: str = ""
    trust_level: str = "TRUSTED"
    verified: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "version": self.version,
            "author": self.author,
            "stars": self.stars,
            "downloads": self.downloads,
            "tags": self.tags,
            "install_url": self.install_url,
            "install_method": self.install_method,
            "subdirectory": self.subdirectory,
            "trust_level": self.trust_level,
            "verified": self.verified,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StaticSkillItem:
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            source=str(data.get("source", "clawhub")),
            version=str(data.get("version", "1.0.0")),
            author=str(data.get("author", "")),
            stars=int(data.get("stars", 0)),
            downloads=int(data.get("downloads", 0)),
            tags=list(data.get("tags", [])),
            install_url=str(data.get("install_url", "")),
            install_method=str(data.get("install_method", "zip")),
            subdirectory=str(data.get("subdirectory", "")),
            trust_level=str(data.get("trust_level", "TRUSTED")),
            verified=bool(data.get("verified", True)),
        )


@dataclass(slots=True)
class StaticIndexManifest:
    """Header and metadata of static skills index."""

    version: str = "1.0"
    updated_at: str = ""
    total_skills: int = 0
    sha256: str = ""
    skills: list[StaticSkillItem] = field(default_factory=list)
