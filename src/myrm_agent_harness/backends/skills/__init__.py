"""Skill Backend Implementations

[INPUT]
- protocols::SkillBackendProtocol (POS: 技能后端协议，定义技能加载接口契约)
- creation_protocols::SkillWriteBackend, SkillSaveResult, SkillDeleteResult, SkillResourceWriteResult (POS: 技能写入后端协议)
- discovery_protocols::SkillDiscoveryBackend, SkillSearchResult, SkillInstallResult (POS: 技能发现后端协议)
- scanning_write_backend::ScanningSkillWriteBackend (POS: 安全扫描写入后端包装类)
- local::LocalSkillBackend (POS: 本地技能后端，从文件系统加载)
- storage::StorageSkillBackend (POS: 存储技能后端，从存储桶加载)
- memory::InMemorySkillBackend (POS: 内存技能后端，用于动态技能)
- composite::CompositeSkillBackend (POS: 混合技能后端，组合多个后端)
- factory::SkillBackend (POS: 技能后端工厂类，简化创建)

[OUTPUT]
- SkillBackendProtocol: 技能后端协议（已安装技能的 list/load/content/resources）
- SkillWriteBackend: 技能写入后端协议（用户自创技能的 save/delete/write_resource/delete_resource）
- SkillSaveResult: 技能保存结果
- SkillDeleteResult: 技能删除结果
- SkillResourceWriteResult: 辅助文件写入/删除结果
- ScanningSkillWriteBackend: 安全扫描写入后端包装类
- SkillDiscoveryBackend: 技能发现后端协议（外部技能的 search/install）
- SkillSearchResult: 技能搜索结果
- SkillInstallResult: 技能安装结果
- LocalSkillBackend: 本地技能后端（开发环境首选）
- StorageSkillBackend: 存储技能后端（生产环境首选）
- InMemorySkillBackend: 内存技能后端（MCP 等动态技能）
- CompositeSkillBackend: 混合技能后端（路由和回退）
- SkillBackend: 工厂类（推荐使用）

[POS]
Skill backend implementations module. Provides multiple backend implementations and three core protocols for loading skills from various sources.

"""

from myrm_agent_harness.backends.skills.composite import CompositeSkillBackend
from myrm_agent_harness.backends.skills.creation_protocols import (
    SkillDeleteResult,
    SkillResourceWriteResult,
    SkillSaveResult,
    SkillWriteBackend,
)
from myrm_agent_harness.backends.skills.decorators import (
    QuarantineAwareSkillBackend,
    VersionAwareSkillBackend,
    session_id_var,
)
from myrm_agent_harness.backends.skills.discovery_protocols import (
    SkillDiscoveryBackend,
    SkillInstallResult,
    SkillSearchResult,
)
from myrm_agent_harness.backends.skills.factory import SkillBackend
from myrm_agent_harness.backends.skills.local import LocalSkillBackend, scan_workspace_skills
from myrm_agent_harness.backends.skills.memory import InMemorySkillBackend
from myrm_agent_harness.backends.skills.permission_templates import (
    TEMPLATE_PERMISSIONS,
    PermissionTemplate,
    get_template_permissions,
)
from myrm_agent_harness.backends.skills.permission_validator import (
    SkillPermission,
    check_permission_for_tool_call,
    log_permission_usage,
    map_permission_to_skill_permission,
    set_permission_usage_callback,
    validate_skill_permissions,
)
from myrm_agent_harness.backends.skills.protocols import (
    ABTestStoreProtocol,
    SkillStateReader,
    SnapshotStoreProtocol,
)
from myrm_agent_harness.backends.skills.protocols import (
    SkillBackend as SkillBackendProtocol,
)
from myrm_agent_harness.backends.skills.scanning_write_backend import ScanningSkillWriteBackend
from myrm_agent_harness.backends.skills.storage import StorageSkillBackend
from myrm_agent_harness.backends.skills.types import skill_visible_for_tools

__all__ = [
    "TEMPLATE_PERMISSIONS",
    "ABTestStoreProtocol",
    "CompositeSkillBackend",
    "InMemorySkillBackend",
    "LocalSkillBackend",
    # Permission templates
    "PermissionTemplate",
    # Decorators
    "QuarantineAwareSkillBackend",
    "ScanningSkillWriteBackend",
    "SkillBackend",
    "SkillBackendProtocol",
    "SkillDeleteResult",
    "SkillDiscoveryBackend",
    "SkillInstallResult",
    # Permission system
    "SkillPermission",
    "SkillResourceWriteResult",
    "SkillSaveResult",
    "SkillSearchResult",
    "SkillStateReader",
    "SkillWriteBackend",
    "SnapshotStoreProtocol",
    "StorageSkillBackend",
    "VersionAwareSkillBackend",
    "check_permission_for_tool_call",
    "get_template_permissions",
    "log_permission_usage",
    "map_permission_to_skill_permission",
    "scan_workspace_skills",
    "session_id_var",
    "set_permission_usage_callback",
    "skill_visible_for_tools",
    "validate_skill_permissions",
]
