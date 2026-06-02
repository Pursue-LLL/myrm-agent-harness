"""MCP 技能代理服务

提供 MCP 技能调用的核心逻辑（纯 Python）。
IPC Server 内部使用此服务处理子进程的 MCP 工具调用请求。

特性：
- 相同参数的调用会被缓存 10 分钟，避免重复调用浪费资源
- 提供 handle_mcp_invoke() 函数供 IPC Proxy 和自定义集成使用

[INPUT]
- utils.lru_cache::LRUCache (POS: LRU  TTL  LRU)
- backends.skills.types::SkillMetadata (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- toolkits.mcp::MCPConfig (POS: MCP toolkit entry point. Aggregates client management, agent tool fetching, connection pooling, configuration, and security validation for unified MCP protocol support.)
- toolkits.mcp.client::MCPServerConfigProtocol (POS: MCP client management layer. Handles MCP server connection setup, transport config conversion, and multi-server client initialization with optional auth injection.)

[OUTPUT]
- MCPSkillProxyService: class — M C P Skill Proxy Service
- MCPInvokeResult: class — M C P Invoke Result
- get_mcp_skill_proxy_service: function — get_mcp_skill_proxy_service
- handle_mcp_invoke: Args:

[POS]
Provides MCPSkillProxyService, MCPInvokeResult, get_mcp_skill_proxy_service.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import TYPE_CHECKING, TypedDict

from myrm_agent_harness.utils.lru_cache import LRUCache

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.types import SkillMetadata
    from myrm_agent_harness.toolkits.mcp import MCPConfig

logger = logging.getLogger(__name__)

# 缓存有效期（秒）
CACHE_TTL_SECONDS = 600  # 10 分钟


class MCPSkillProxyService:
    """MCP 技能代理服务

    专门处理 MCP 技能的调用，封装所有调用逻辑：
    - 从 skill_registry 获取配置
    - 工具查找（按服务器名+工具名匹配）
    - 工具调用
    - 结果解析
    - 相同参数的调用缓存（10 分钟有效期）
    """

    def __init__(self) -> None:
        """初始化代理服务"""
        self._cache: LRUCache[object] = LRUCache(maxsize=1000, ttl=CACHE_TTL_SECONDS, id="mcp_skill_cache")

    def _make_cache_key(self, skill_name: str, tool_name: str, params: dict[str, object]) -> str:
        """生成缓存键

        Args:
            skill_name: 技能名称
            tool_name: 工具名称
            params: 工具参数

        Returns:
            缓存键字符串
        """
        # 将参数序列化为 JSON 并计算哈希
        params_json = json.dumps(params, sort_keys=True, ensure_ascii=False)
        params_hash = hashlib.md5(params_json.encode()).hexdigest()[:16]
        return f"{skill_name}.{tool_name}:{params_hash}"

    async def invoke_tool(
        self, skill_name: str, tool_name: str, params: dict[str, object], *, trace_id: str = "-"
    ) -> object:
        """调用 MCP 工具

        从 skill_registry 获取技能配置并调用对应的 MCP 工具。
        技能必须在 Agent 初始化时已通过 mcp_skill_generator 注册。

        相同参数的调用会被缓存 10 分钟，避免重复调用浪费资源。

        Args:
            skill_name: 技能名称
            tool_name: 工具名称
            params: 工具参数
            trace_id: PTC 调用链追踪 ID

        Returns:
            工具返回结果

        Raises:
            RuntimeError: 如果找不到技能或工具
        """
        log_prefix = f"[PTC:{trace_id}]"
        cleaned_params = {k: v for k, v in params.items() if v is not None}
        cache_key = self._make_cache_key(skill_name, tool_name, cleaned_params)
        cached_result = self._cache.get(cache_key)
        if cached_result is not None:
            logger.info(f"{log_prefix} Cache hit: {skill_name}.{tool_name}")
            return cached_result

        logger.info(f"{log_prefix} Invoking: {skill_name}.{tool_name}")
        logger.debug(f"{log_prefix} Params: {cleaned_params}")

        t0 = time.monotonic()
        result = await self._invoke_from_registry(skill_name, tool_name, cleaned_params)
        elapsed_ms = (time.monotonic() - t0) * 1000

        self._cache.set(cache_key, result)

        logger.info(f"{log_prefix} MCP {skill_name}.{tool_name} completed in {elapsed_ms:.0f}ms")
        return result

    # =========================================================================
    # 调用实现
    # =========================================================================

    async def _invoke_from_registry(self, skill_name: str, tool_name: str, params: dict[str, object]) -> object:
        """从 skill_registry 获取配置并调用工具

        Args:
            skill_name: 技能名称
            tool_name: 工具名称
            params: 工具参数

        Returns:
            工具返回结果

        Raises:
            RuntimeError: 如果找不到技能或技能不是 MCP 技能
        """
        from myrm_agent_harness.agent.skills.runtime.registry import skill_registry

        skill_meta = skill_registry.get_skill(skill_name)
        if not skill_meta:
            raise RuntimeError(f"Skill not found: {skill_name}")

        if not skill_meta.is_mcp_skill:
            raise RuntimeError(f"Skill '{skill_name}' is not an MCP skill")

        mcp_config = self._convert_skill_meta_config(skill_meta)
        # 从 mcp.server 获取服务器名
        assert skill_meta.mcp is not None
        mcp_server = skill_meta.mcp.server

        return await self._find_and_invoke(mcp_config, mcp_server, tool_name, params)

    async def _find_and_invoke(
        self, mcp_config: list[MCPConfig], mcp_server: str, tool_name: str, params: dict[str, object]
    ) -> object:
        """Invoke an MCP tool on the warm pooled session.

        The connection manager keeps one persistent, already-initialized session
        per server, so the call reuses the live process/connection instead of
        spawning a fresh subprocess and re-running ``initialize`` each time.
        Server- and tool-name variant resolution is handled by the connection.

        Raises:
            RuntimeError: if the target server or tool cannot be found.
        """
        from typing import cast

        from myrm_agent_harness.toolkits.mcp.client import MCPServerConfigProtocol
        from myrm_agent_harness.toolkits.mcp.connection_manager import get_mcp_connection_manager

        manager = await get_mcp_connection_manager()
        # MCPConfig implements MCPServerConfigProtocol — safe structural cast.
        config_as_protocol = cast("list[MCPServerConfigProtocol]", mcp_config)
        conn = await manager.get_connection(config_as_protocol)

        raw_result = await conn.call(mcp_server, tool_name, params)
        return self.parse_mcp_result(raw_result)

    # =========================================================================
    # 配置转换
    # =========================================================================

    def _convert_skill_meta_config(self, skill_meta: SkillMetadata) -> list[MCPConfig]:
        """从技能元数据中提取并转换 MCP 配置

        Args:
            skill_meta: 技能元数据

        Returns:
            转换后的 MCPConfig 列表

        Raises:
            RuntimeError: 如果技能不是 MCP 技能或配置缺失
        """
        from myrm_agent_harness.toolkits.mcp import MCPConfig

        if not skill_meta.is_mcp_skill or not skill_meta.mcp:
            raise RuntimeError(f"Skill '{skill_meta.name}' is not an MCP skill")

        # 从 mcp.config 中获取配置
        mcp_config_raw = skill_meta.mcp.config
        if not mcp_config_raw:
            raise RuntimeError(f"mcp_config not found in skill metadata for: {skill_meta.name}")

        mcp_config: list[MCPConfig] = []
        for cfg in mcp_config_raw:
            if isinstance(cfg, dict):
                # 类型忽略：cfg 是 dict，但具体类型未知
                mcp_config.append(MCPConfig(**cfg))  # type: ignore[arg-type]
            elif isinstance(cfg, MCPConfig):
                mcp_config.append(cfg)
        return mcp_config

    # =========================================================================
    # 结果解析
    # =========================================================================

    def parse_mcp_result(self, raw_result: object) -> object:
        """解析 MCP 工具返回结果

        MCP 返回格式可能是：
        - 元组 (content, artifact)
        - 字符串列表
        - 字典 {'type': 'text', 'text': '...', 'id': '...'} - 需要提取 text 字段
        - 纯字符串
        """
        # 处理元组格式 (content, artifact)
        if isinstance(raw_result, tuple) and len(raw_result) >= 1:
            content = raw_result[0]
        else:
            content = raw_result

        # 如果是字符串列表
        if isinstance(content, list):
            parsed_items = []
            for item in content:
                if isinstance(item, str):
                    try:
                        parsed_items.append(json.loads(item))
                    except (json.JSONDecodeError, ValueError):
                        parsed_items.append(item)
                else:
                    parsed_items.append(item)

            if len(parsed_items) == 1:
                return self._extract_text_content(parsed_items[0])

            if all(isinstance(item, str) for item in content):
                combined = "".join(content)
                try:
                    return self._extract_text_content(json.loads(combined))
                except (json.JSONDecodeError, ValueError):
                    pass

            return [self._extract_text_content(item) for item in parsed_items]

        # 如果是字符串
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
                return self._extract_text_content(parsed)
            except (json.JSONDecodeError, ValueError):
                return content

        return self._extract_text_content(content)

    def _extract_text_content(self, content: object) -> object:
        """提取 MCP 内容中的实际数据

        MCP 返回的内容可能是 {'type': 'text', 'text': '...', 'id': '...'} 格式，
        我们只需要 'text' 字段的值。如果 text 是 JSON 字符串，则解析它。

        Args:
            content: MCP 返回的内容

        Returns:
            提取后的实际数据
        """
        if not isinstance(content, dict):
            return content

        # 检查是否是 MCP 文本内容格式
        if content.get("type") == "text" and "text" in content:
            text_value = content["text"]
            # 尝试解析 text 字段中的 JSON
            if isinstance(text_value, str):
                try:
                    return json.loads(text_value)
                except (json.JSONDecodeError, ValueError):
                    return text_value
            return text_value

        # 不是 MCP 格式，返回原内容
        return content


# =============================================================================
# 全局单例
# =============================================================================

_service: MCPSkillProxyService | None = None


def get_mcp_skill_proxy_service() -> MCPSkillProxyService:
    """获取 MCP 技能代理服务单例"""
    global _service
    if _service is None:
        _service = MCPSkillProxyService()
    return _service


class MCPInvokeResult(TypedDict, total=False):
    """handle_mcp_invoke() 的返回类型"""

    success: bool
    result: object
    error: str


async def handle_mcp_invoke(skill_name: str, tool_name: str, params: dict[str, object]) -> MCPInvokeResult:
    """处理 MCP 工具调用（纯 Python，Web 框架无关）

    被 IPC Proxy 内部调用，也可供自定义集成使用。

    Args:
        skill_name: 技能名称
        tool_name: 工具名称
        params: 工具参数

    Returns:
        MCPInvokeResult: {"success": True, "result": ...} 或 {"success": False, "error": "..."}
    """
    try:
        service = get_mcp_skill_proxy_service()
        result = await service.invoke_tool(skill_name, tool_name, params)
        return MCPInvokeResult(success=True, result=result)
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.warning(f"handle_mcp_invoke failed: {skill_name}.{tool_name}, error: {error_msg}")
        return MCPInvokeResult(success=False, error=error_msg)
