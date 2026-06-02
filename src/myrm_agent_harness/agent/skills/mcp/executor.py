"""PTC 执行器

负责 PTC（Programmatic Tool Calling）检测、代码预处理和执行准备。

核心职责：
1. 检测命令中是否包含 PTC 调用（skills.xxx 或 tools.xxx）
2. 获取技能的 MCP 配置
3. 将 IPC 客户端代码注入到用户代码中
4. 返回预处理后的代码供 executor 执行

[INPUT]
- toolkits.code_execution::MCPConfigItem (POS: Code execution toolkit entry point. Aggregates execution configuration, executor implementations, workspace management, and factory functions for the Agent-in-Sandbox architecture.)

[OUTPUT]
- SkillExecutionContext: class — Skill Execution Context
- SkillExecutor: class — Skill Executor

[POS]
Provides SkillExecutionContext, SkillExecutor.
"""

import logging
import re
from dataclasses import dataclass

from myrm_agent_harness.agent.skills.mcp.python_extractor import (
    SKILL_IMPORT_RE as SKILL_NAME_PATTERN,
)
from myrm_agent_harness.agent.skills.mcp.python_extractor import (
    TOOLS_IMPORT_RE as TOOLS_IMPORT_PATTERN,
)
from myrm_agent_harness.toolkits.code_execution import MCPConfigItem

logger = logging.getLogger(__name__)

# 用于重写缺少 skills. 前缀的 import 语句
# 匹配 "from xxx_skill import" 但不匹配 "from skills.xxx_skill import"
_BARE_SKILL_IMPORT_PATTERN = re.compile(r"from\s+([\w]+_skill)\s+import")


@dataclass
class SkillExecutionContext:
    """技能执行上下文

    包含技能执行所需的所有信息
    """

    is_skill: bool
    """是否是技能调用"""

    skill_name: str | None
    """技能名称"""

    mcp_config: list[MCPConfigItem] | None
    """MCP 配置"""

    original_code: str
    """原始代码"""

    prepared_code: str
    """预处理后的代码（包含 MCP 代理客户端）"""


class SkillExecutor:
    """技能执行器

    负责：
    1. 检测命令中是否包含技能调用
    2. 获取技能的 MCP 配置
    3. 将 MCP 代理客户端代码注入到用户代码中
    """

    def __init__(self, api_prefix: str = "/api/v1"):
        """初始化技能执行器

        Args:
            api_prefix: API 前缀（默认 /api/v1，可通过参数配置）
        """
        self.api_prefix = api_prefix

    def prepare_for_execution(
        self,
        command: str,
        ipc_socket_path: str,
        session_id: str | None = None,
        workspace_root: str | None = None,
    ) -> SkillExecutionContext:
        """准备代码执行

        检测命令中是否包含技能调用，如果是则：
        1. 提取 Python 代码
        2. 注入 MCP IPC 客户端代码（携带 session_id / workspace_root 以支持
           session_store / notify 等需要会话上下文的 builtin 工具）
        3. 返回预处理后的代码

        Args:
            command: Bash 命令（如 python -c "..."）
            ipc_socket_path: IPC Unix Socket 路径
            session_id: 当前会话 ID（用于 builtin 会话上下文）
            workspace_root: 沙箱挂载的工作目录（host 视角的绝对路径）

        Returns:
            SkillExecutionContext 包含预处理后的代码
        """
        is_ptc, identifier = self.detect_skill_in_command(command)

        if not is_ptc or not identifier:
            return SkillExecutionContext(
                is_skill=False, skill_name=None, mcp_config=None, original_code=command, prepared_code=command
            )

        python_code = self._extract_python_code(command)
        if not python_code:
            return SkillExecutionContext(
                is_skill=False, skill_name=None, mcp_config=None, original_code=command, prepared_code=command
            )

        from myrm_agent_harness.agent.skills.mcp.builtin_registry import BUILTIN_SKILL_NAME

        mcp_config = None
        if identifier == BUILTIN_SKILL_NAME:
            logger.info("Detected PTC builtin tools import")
        else:
            mcp_config = self.get_skill_mcp_config(identifier)
            logger.info(f"Detected MCP skill: {identifier}")

        python_code = self._rewrite_skill_imports(python_code)
        ipc_client_code = self._generate_mcp_client_code(
            ipc_socket_path,
            session_id=session_id,
            workspace_root=workspace_root,
        )
        prepared_code = f"{ipc_client_code}\n\n# === User Code ===\n{python_code}"

        return SkillExecutionContext(
            is_skill=True,
            skill_name=identifier,
            mcp_config=mcp_config,
            original_code=command,
            prepared_code=prepared_code,
        )

    def detect_skill_in_command(self, command: str) -> tuple[bool, str | None]:
        """检测命令中是否包含 PTC 调用（MCP 技能或内置工具）

        主要检测 python -c "..." 形式的命令中的 PTC 调用

        Args:
            command: Bash 命令

        Returns:
            (is_ptc, skill_name) - 是否是 PTC 调用，技能名称（内置工具返回 "__builtin__"）
        """
        python_code = self._extract_python_code(command)
        if not python_code:
            return False, None

        return self._detect_ptc_in_code(python_code)

    def _detect_ptc_in_code(self, code: str) -> tuple[bool, str | None]:
        """检测代码中是否包含 PTC 调用

        优先检测 MCP 技能，再检测内置工具。

        Args:
            code: Python 代码

        Returns:
            (is_ptc, identifier) - 是否是 PTC 调用，MCP 技能名或 "__builtin__"
        """
        skill_match = SKILL_NAME_PATTERN.search(code)
        if skill_match:
            return True, skill_match.group(1)

        if TOOLS_IMPORT_PATTERN.search(code):
            from myrm_agent_harness.agent.skills.mcp.builtin_registry import BUILTIN_SKILL_NAME

            return True, BUILTIN_SKILL_NAME

        return False, None

    def _rewrite_skill_imports(self, code: str) -> str:
        """重写缺少 skills. 前缀的 import 语句

        LLM 可能生成 "from mcp_xxx_skill import yyy" 而不是
        "from skills.mcp_xxx_skill import yyy"。动态模块系统的
        import hook 只拦截 skills.* 前缀，所以需要自动补全前缀。

        注意：_BARE_SKILL_IMPORT_PATTERN 使用 [\\w]+ 匹配模块名，
        而 "." 不属于 \\w 字符，所以 "from skills.xxx_skill import"
        不会被误匹配（正则无法跨越 "." 匹配到 xxx_skill 部分）。

        Args:
            code: 原始 Python 代码

        Returns:
            重写后的代码
        """
        rewritten = _BARE_SKILL_IMPORT_PATTERN.sub(
            lambda m: m.group(0).replace(f"from {m.group(1)}", f"from skills.{m.group(1)}"), code
        )
        if rewritten != code:
            logger.info("Rewrote import: added skills. prefix")
        return rewritten

    def get_skill_mcp_config(self, skill_name: str) -> list[MCPConfigItem] | None:
        """获取技能的 MCP 配置

        Args:
            skill_name: 技能名称

        Returns:
            MCP 配置列表，如果技能不存在或不是 MCP 技能则返回 None
        """
        from myrm_agent_harness.agent.skills.runtime.registry import skill_registry

        skill_meta = skill_registry.get_skill(skill_name)
        if not skill_meta or not skill_meta.is_mcp_skill or not skill_meta.mcp:
            return None

        # 从 skill_meta.mcp.config 中获取配置
        config_obj = skill_meta.mcp.config
        if not config_obj or not isinstance(config_obj, list):
            return None

        return MCPConfigItem.from_dict_list(config_obj)

    def detect_and_prepare(self, command: str) -> tuple[bool, list[MCPConfigItem] | None]:
        """检测 PTC 调用并获取 MCP 配置

        结合 detect_skill_in_command 和 get_skill_mcp_config 的便捷方法

        Args:
            command: Bash 命令

        Returns:
            (is_mcp_skill, mcp_config_items) 元组
        """
        is_skill, skill_name = self.detect_skill_in_command(command)
        if not is_skill or not skill_name:
            return False, None

        mcp_config = self.get_skill_mcp_config(skill_name)
        if mcp_config:
            logger.info(f"Detected MCP skill: {skill_name}")

        return True, mcp_config

    def _extract_python_code(self, command: str) -> str | None:
        """从 Bash 命令中提取 Python 代码（委托给统一提取器）。"""
        from myrm_agent_harness.agent.skills.mcp.python_extractor import (
            extract_python_from_bash,
        )

        return extract_python_from_bash(command)

    def _generate_mcp_client_code(
        self,
        ipc_socket_path: str,
        session_id: str | None = None,
        workspace_root: str | None = None,
    ) -> str:
        """生成 MCP IPC 客户端代码

        通过 Unix Socket 与 Agent 主进程通信。

        Args:
            ipc_socket_path: IPC Unix Socket 路径
            session_id: 当前会话 ID
            workspace_root: 沙箱挂载的工作目录

        Returns:
            MCP 客户端代码字符串
        """
        from myrm_agent_harness.agent.skills.mcp.client_templates import generate_ipc_client_code

        return generate_ipc_client_code(
            ipc_socket_path,
            session_id=session_id,
            workspace_root=workspace_root,
        )


# 全局实例（使用默认 API 前缀）
skill_executor = SkillExecutor()
