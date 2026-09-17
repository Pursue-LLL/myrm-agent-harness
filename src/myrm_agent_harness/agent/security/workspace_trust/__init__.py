"""Unified workspace trust gate — folder bind + side-channel execution control.

[INPUT]
- agent.security.workspace_trust.context::clear_workspace_trust_context,
  get_repo_command_prefixes, get_workspace_trust_level, set_repo_command_prefixes,
  set_workspace_trust_level (POS: 运行期信任上下文变量)
- agent.security.workspace_trust.errors::WorkspaceTrustBlockedError
  (POS: 信任门禁错误契约)
- agent.security.workspace_trust.gate::assert_mcp_spawn_allowed,
  blocks_workspace_side_channels, is_path_within_workspace, matches_repo_command_prefix
  (POS: 纯谓词门禁层)
- agent.security.workspace_trust.manifest::build_workspace_trust_manifest,
  canonicalize_workspace_path, manifest_hash (POS: 绑定前披露载荷构建层)
- agent.security.workspace_trust.protocol::WorkspaceTrustLookup
  (POS: 服务端注册表注入协议)
- agent.security.workspace_trust.provider::get_workspace_trust_lookup,
  resolve_workspace_trust_level, set_workspace_trust_lookup
  (POS: 查找注册表解析层)
- agent.security.workspace_trust.repo_policy::load_repo_command_prefixes
  (POS: 仓库声明命令前缀读取层)
- agent.security.workspace_trust.runtime::apply_workspace_trust_for_root,
  clear_workspace_trust_runtime (POS: 运行生命周期绑定层)
- agent.security.workspace_trust.types::WorkspaceTrustEntry, WorkspaceTrustLevel,
  WorkspaceTrustManifest (POS: 信任级别与披露载荷类型)

[OUTPUT]
- Gate API: blocks_workspace_side_channels, assert_mcp_spawn_allowed,
  is_path_within_workspace, matches_repo_command_prefix
- Lifecycle API: apply_workspace_trust_for_root, clear_workspace_trust_runtime
- Lookup seam: WorkspaceTrustLookup, set/get_workspace_trust_lookup,
  resolve_workspace_trust_level
- Types: WorkspaceTrustLevel, WorkspaceTrustManifest, WorkspaceTrustEntry

[POS]
Public surface of the workspace_trust subpackage. Import from here rather than from the
individual modules so the internal layout stays free to change. Located under
`agent/security/`, deliberately not in `toolkits/`; the server owns persistence and REST,
the control plane is untouched.
"""

from __future__ import annotations

from .context import (
    clear_workspace_trust_context,
    get_repo_command_prefixes,
    get_workspace_trust_level,
    set_repo_command_prefixes,
    set_workspace_trust_level,
)
from .errors import WorkspaceTrustBlockedError
from .gate import (
    assert_mcp_spawn_allowed,
    blocks_workspace_side_channels,
    is_path_within_workspace,
    matches_repo_command_prefix,
)
from .manifest import build_workspace_trust_manifest, canonicalize_workspace_path, manifest_hash
from .protocol import WorkspaceTrustLookup
from .provider import (
    get_workspace_trust_lookup,
    resolve_workspace_trust_level,
    set_workspace_trust_lookup,
)
from .repo_policy import load_repo_command_prefixes
from .runtime import apply_workspace_trust_for_root, clear_workspace_trust_runtime
from .types import WorkspaceTrustEntry, WorkspaceTrustLevel, WorkspaceTrustManifest

__all__ = [
    "WorkspaceTrustBlockedError",
    "WorkspaceTrustEntry",
    "WorkspaceTrustLevel",
    "WorkspaceTrustLookup",
    "WorkspaceTrustManifest",
    "apply_workspace_trust_for_root",
    "assert_mcp_spawn_allowed",
    "blocks_workspace_side_channels",
    "build_workspace_trust_manifest",
    "canonicalize_workspace_path",
    "clear_workspace_trust_context",
    "clear_workspace_trust_runtime",
    "get_repo_command_prefixes",
    "get_workspace_trust_level",
    "get_workspace_trust_lookup",
    "is_path_within_workspace",
    "load_repo_command_prefixes",
    "manifest_hash",
    "matches_repo_command_prefix",
    "resolve_workspace_trust_level",
    "set_repo_command_prefixes",
    "set_workspace_trust_level",
    "set_workspace_trust_lookup",
]
