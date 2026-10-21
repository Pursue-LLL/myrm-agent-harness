"""PTC IPC 客户端代码模板

为子进程生成 IPC 客户端代码，通过 Unix Socket 与 Agent 主进程通信。
Agent-in-Sandbox 模式下，代码通过 subprocess 执行，需要 IPC 回调主进程。

支持两个命名空间：
- skills.xxx_skill.yyy() → MCP 工具（skill_name = 实际技能名）
- tools.xxx.yyy() → 内置工具（skill_name = "__builtin__"）

特性：
- 异步调用，支持 asyncio.gather() 并发
- 统一错误处理
- 自动重试（连接错误时）
- 总超时控制
- 注入 ``_SESSION_ID`` / ``_WORKSPACE_ROOT`` 常量并随每次请求上报，
  让主进程内的 builtin handler 能解析 per-session 状态目录。

[INPUT]
- (none)

[OUTPUT]
- MCPError: PTC 调用错误（在子进程中抛出）。
- generate_ipc_client_code(socket_path, session_id, agent_id, workspace_root): 生成完整客户端源码。

[POS]
PTC 子进程注入的 IPC 客户端代码生成器。负责构造 ``tools.*`` /
``skills.*`` 命名空间所需的 stub 模块以及底层 Unix Socket 客户端。
"""

import json

MAX_RETRIES = 1
RETRY_DELAY = 0.5
TOTAL_TIMEOUT = 90
TRACE_PREVIEW_CHARS = 2000


def _generate_base_code() -> str:
    """生成基础代码（错误类 + 配置 + 重试逻辑）"""
    return f'''
# === MCP Client Base ===
class MCPError(Exception):
    """MCP 调用错误"""
    def __init__(self, msg: str, skill: str = "", tool: str = "", retryable: bool = False):
        self.msg, self.skill, self.tool, self.retryable = msg, skill, tool, retryable
        super().__init__(f"[{{skill}}.{{tool}}] {{msg}}" if skill else msg)

# 重试配置
MAX_RETRIES = {MAX_RETRIES}
RETRY_DELAY = {RETRY_DELAY}
TOTAL_TIMEOUT = {TOTAL_TIMEOUT}
_TRACE_PREVIEW_CHARS = {TRACE_PREVIEW_CHARS}

async def _retry_call(call_fn, skill: str, tool: str):
    """通用重试逻辑"""
    import time
    start, retries, last_err = time.time(), 0, None

    while retries <= MAX_RETRIES:
        if time.time() - start > TOTAL_TIMEOUT:
            raise MCPError(f"Timeout ({{TOTAL_TIMEOUT}}s)", skill, tool)
        try:
            return await call_fn()
        except MCPError as e:
            if not e.retryable:
                raise
            last_err = e
            retries += 1
            if retries <= MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * retries)
        except Exception as e:
            raise MCPError(f"{{type(e).__name__}}: {{e}}", skill, tool)

    err_detail = f" (last error: {{last_err.msg}})" if last_err else ""
    raise MCPError(f"Failed after {{MAX_RETRIES}} retries{{err_detail}}", skill, tool)
'''


def _generate_tools_module_system() -> str:
    """生成 tools 命名空间的动态模块系统（tools.xxx 支持）"""
    return '''
# === Tools Dynamic Module System (PTC Built-in Tools) ===
class _ToolFunction:
    """内置工具函数代理"""
    __slots__ = ("_name")

    def __init__(self, name: str):
        self._name = name

    async def __call__(self, **kwargs):
        return await _call("__builtin__", self._name, kwargs)

class _ToolModule(types.ModuleType):
    """内置工具模块代理"""
    def __init__(self, name: str):
        super().__init__(f"tools.{name}")
        self._module_name = name
        self._functions: dict[str, _ToolFunction] = {}
        self.__package__ = "tools"

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._functions:
            self._functions[name] = _ToolFunction(name)
        return self._functions[name]

class _ToolsPackage(types.ModuleType):
    """tools 包代理"""
    def __init__(self):
        super().__init__("tools")
        self.__path__ = []
        self.__package__ = "tools"
        self._modules: dict[str, _ToolModule] = {}

    def _get_module(self, name: str) -> _ToolModule:
        if name not in self._modules:
            mod = _ToolModule(name)
            self._modules[name] = mod
            sys.modules[f"tools.{name}"] = mod
        return self._modules[name]

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._get_module(name)

class _ToolsImportFinder(MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "tools":
            return ModuleSpec(fullname, _ToolsImportLoader(), is_package=True)
        if fullname.startswith("tools."):
            return ModuleSpec(fullname, _ToolsImportLoader())
        return None

class _ToolsImportLoader(Loader):
    def create_module(self, spec):
        if spec.name == "tools":
            if "tools" not in sys.modules:
                sys.modules["tools"] = _ToolsPackage()
            return sys.modules["tools"]
        parts = spec.name.split(".")
        if len(parts) == 2:
            pkg = sys.modules.get("tools")
            if pkg is None:
                pkg = _ToolsPackage()
                sys.modules["tools"] = pkg
            return pkg._get_module(parts[1])
        return None

    def exec_module(self, module):
        pass

sys.meta_path.insert(0, _ToolsImportFinder())
'''


def _generate_module_system() -> str:
    """生成动态模块系统（skills.xxx 支持）"""
    return '''
# === Dynamic Module System ===
class _SkillFunction:
    """技能函数代理"""
    __slots__ = ("_skill", "_func")

    def __init__(self, skill: str, func: str):
        self._skill, self._func = skill, func

    async def __call__(self, **kwargs):
        # 将下划线转为连字符（Python 命名 -> MCP 工具名）
        tool_name = self._func.replace("_", "-")
        return await _call(self._skill, tool_name, kwargs)

class _SkillModule(types.ModuleType):
    """技能模块代理"""
    def __init__(self, name: str):
        super().__init__(f"skills.{name}")
        self._skill_name = name
        self._functions: dict[str, _SkillFunction] = {}
        self.__package__ = "skills"
        self.__path__: list[str] = []

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._functions:
            self._functions[name] = _SkillFunction(self._skill_name, name)
        return self._functions[name]

class _SkillsPackage(types.ModuleType):
    """skills 包代理"""
    def __init__(self):
        super().__init__("skills")
        self.__path__ = []
        self.__package__ = "skills"
        self._modules: dict[str, _SkillModule] = {}

    def _get_module(self, name: str) -> _SkillModule:
        if name not in self._modules:
            mod = _SkillModule(name)
            self._modules[name] = mod
            sys.modules[f"skills.{name}"] = mod
        return self._modules[name]

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._get_module(name)

# Import hook 支持 "from skills.xxx import yyy" 语法
from importlib.abc import MetaPathFinder, Loader
from importlib.machinery import ModuleSpec

class _SkillsImportFinder(MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "skills":
            return ModuleSpec(fullname, _SkillsImportLoader(), is_package=True)
        if fullname.startswith("skills."):
            parts = fullname.split(".")
            is_pkg = len(parts) == 2
            return ModuleSpec(fullname, _SkillsImportLoader(), is_package=is_pkg)
        return None

class _SkillsImportLoader(Loader):
    def create_module(self, spec):
        if spec.name == "skills":
            if "skills" not in sys.modules:
                sys.modules["skills"] = _SkillsPackage()
            return sys.modules["skills"]
        parts = spec.name.split(".")
        pkg = sys.modules.get("skills")
        if pkg is None:
            pkg = _SkillsPackage()
            sys.modules["skills"] = pkg
        if len(parts) == 2:
            return pkg._get_module(parts[1])
        if len(parts) == 3:
            skill_mod = pkg._get_module(parts[1])
            return skill_mod
        return None

    def exec_module(self, module):
        pass  # 模块已在 create_module 中设置

# 安装 import hook
sys.meta_path.insert(0, _SkillsImportFinder())
'''


def generate_ipc_client_code(
    socket_path: str,
    session_id: str | None = None,
    agent_id: str | None = None,
    workspace_root: str | None = None,
    read_only_tools: frozenset[str] | None = None,
    auth_token: str | None = None,
    readonly_workspace: bool = False,
    trace_nonce: str | None = None,
    tcp_port: int = 0,
) -> str:
    """生成 Unix Socket IPC 客户端代码。

    Args:
        socket_path: Unix Socket 路径。
        session_id: 当前会话 ID(用于 notify 等需要会话隔离的 builtin)。
        agent_id: 当前 Agent ID(用于 MCP scope-gate 策略匹配，独立于会话 ID)。
        workspace_root: 沙箱内的工作目录(host 视角的绝对路径)。
        read_only_tools: 声明 ``readOnlyHint`` 的 ``skill.tool`` 全名集合。只有这些
            调用允许在网络中断后重试；写操作重放会造成重复副作用。
        auth_token: 服务端下发的进程内 bearer token，缺失时服务端会拒绝请求。
        readonly_workspace: 调用方是否在只读沙箱中运行；服务端据此拒绝写类 MCP 工具。
        trace_nonce: 服务端下发的标记 nonce。宿主只接受带该 nonce 的调用标记，
            因此工具返回的文本无法伪造引用或截断真实标记。缺失时客户端不输出标记
            （宁可不产生元数据，也不产生不可信的元数据）。
        tcp_port: 服务端以 loopback TCP 监听时的端口（Windows 走这条路径）。为 0
            时客户端连接 Unix socket。
    """
    base = _generate_base_code()
    module_system = _generate_module_system()
    tools_module_system = _generate_tools_module_system()

    session_literal = json.dumps(session_id) if session_id is not None else "None"
    agent_literal = json.dumps(agent_id) if agent_id is not None else "None"
    workspace_literal = json.dumps(workspace_root) if workspace_root is not None else "None"
    read_only_literal = json.dumps(sorted(read_only_tools or ()))
    token_literal = json.dumps(auth_token) if auth_token is not None else "None"
    readonly_literal = "True" if readonly_workspace else "False"
    nonce_literal = json.dumps(trace_nonce) if trace_nonce is not None else "None"
    tcp_port_literal = str(tcp_port) if tcp_port else "0"

    return f'''
import sys, types, json, asyncio, uuid, base64

# IPC 配置
_SOCKET_PATH = "{socket_path}"
_TRACE_ID = uuid.uuid4().hex
_SESSION_ID = {session_literal}
_AGENT_ID = {agent_literal}
_WORKSPACE_ROOT = {workspace_literal}
_READ_ONLY_TOOLS = frozenset({read_only_literal})
_AUTH_TOKEN = {token_literal}
_READONLY_WORKSPACE = {readonly_literal}
_TRACE_NONCE = {nonce_literal}
_TCP_PORT = {tcp_port_literal}

{base}
{module_system}
{tools_module_system}

async def _ipc_request(skill: str, tool: str, params: dict):
    """发送单次 IPC 请求"""
    request = {{
        "skill_name": skill,
        "tool_name": tool,
        "params": params,
        "trace_id": _TRACE_ID,
        "session_id": _SESSION_ID,
        "agent_id": _AGENT_ID,
        "workspace_root": _WORKSPACE_ROOT,
        "auth_token": _AUTH_TOKEN,
        "readonly_workspace": _READONLY_WORKSPACE,
    }}

    data = json.dumps(request).encode()
    if _TCP_PORT:
        # Windows asyncio uses ProactorEventLoop, which cannot open AF_UNIX streams.
        reader, writer = await asyncio.open_connection("127.0.0.1", _TCP_PORT)
    else:
        reader, writer = await asyncio.open_unix_connection(_SOCKET_PATH)

    try:
        # 发送：4字节长度 + 数据
        writer.write(len(data).to_bytes(4, "big") + data)
        await writer.drain()

        # 接收：4字节长度 + 数据
        resp_len = int.from_bytes(await reader.readexactly(4), "big")
        resp_data = await reader.readexactly(resp_len)
        response = json.loads(resp_data.decode())

        if not response.get("success"):
            _err = MCPError(response.get("error", "Unknown error"), skill, tool)
            # 宿主已明确判定失败：重试无法改变结果，且写操作可能已产生副作用。
            _err.retryable = False
            raise _err
        return response.get("result")
    finally:
        writer.close()
        await writer.wait_closed()

async def _call(skill: str, tool: str, params: dict):
    """IPC 调用入口（带重试）"""
    # 断连类错误可能发生在请求发出之后。只有只读工具能安全重放；
    # 写操作重试会造成重复副作用（重复建单、重复发消息）。
    retry_safe = f"{{skill}}.{{tool}}" in _READ_ONLY_TOOLS

    async def do_call():
        try:
            return await _ipc_request(skill, tool, params)
        except (ConnectionError, BrokenPipeError, FileNotFoundError, asyncio.IncompleteReadError) as e:
            raise MCPError(f"Connection: {{e}}", skill, tool, retryable=retry_safe)

    result = await _retry_call(do_call, skill, tool)
    # Citation trace for the host. Two properties matter:
    # 1. The payload is base64 so no tool result can contain the marker delimiters and
    #    silently truncate or swallow the real marker.
    # 2. The marker carries the host-issued nonce, so text returned by a tool cannot forge
    #    a citation by embedding the delimiters itself.
    if _TRACE_NONCE:
        _preview = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        if len(_preview) > _TRACE_PREVIEW_CHARS:
            _preview = _preview[:_TRACE_PREVIEW_CHARS] + f"...[truncated from {{len(_preview)}} chars]"
        _data = {{"s": skill, "t": tool, "r": _preview}}
        _payload = base64.b64encode(json.dumps(_data, ensure_ascii=False).encode()).decode()
        print(f"__MCP_DATA__{{_TRACE_NONCE}}{{_payload}}__END__{{_TRACE_NONCE}}", flush=True)
    return result
'''
