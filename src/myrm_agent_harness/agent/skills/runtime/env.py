"""技能执行环境准备器

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- pathlib::Path (POS: Python 路径处理库)
- re::re (POS: 正则表达式库)
- backends.skills.types::SkillMetadata (POS: 技能元数据类型)

[OUTPUT]
- extract_skill_name(): 从技能路径中提取技能名称
- prepare_skill_execution_env(): 准备技能执行环境（PYTHONPATH、工作目录）
- rewrite_skill_paths(): 重写代码中的硬编码技能路径
- resolve_skill_env(): 解析技能环境变量（per-skill config + apiKey→primaryEnv 映射）

[POS]
Skill execution environment preparer. Sets up the execution environment before sandbox execution.

"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Claude 标准技能目录模式
CLAUDE_SKILL_PATH_PATTERN = r"\.claude/skills/([^/\s]+)/"


def extract_skill_name(skill_path: str) -> str:
    """从技能路径中提取技能名称

    Args:
        skill_path: 技能存储路径，如 /path/to/skills/prebuilt/web_artifacts_builder

    Returns:
        技能名称，如 web_artifacts_builder
    """
    return skill_path.rstrip("/").split("/")[-1]


def rewrite_skill_paths(command: str, active_skill_names: list[str] | None = None) -> tuple[str, str | None]:
    """重写命令中的技能路径为相对路径

    将硬编码的技能路径（如 .claude/skills/ui-ux-pro-max/scripts/xxx.py）
    转换为相对路径（如 scripts/xxx.py），配合工作目录设置使用。

    支持的转换模式：
    - .claude/skills/{name}/xxx -> xxx
    - python3 .claude/skills/{name}/scripts/xxx.py -> python3 scripts/xxx.py

    Args:
        command: 原始命令
        active_skill_names: 当前激活的技能名称列表（保留参数以保持兼容性，但不再使用）

    Returns:
        元组 (重写后的命令, 检测到的技能名称或None)
        技能名称可用于后续精确设置工作目录
    """
    matches = list(re.finditer(CLAUDE_SKILL_PATH_PATTERN, command))
    if not matches:
        return command, None

    # 提取所有技能名称
    skill_names = [m.group(1) for m in matches]

    # 如果有多个不同的技能，记录警告
    unique_skills = set(skill_names)
    if len(unique_skills) > 1:
        logger.warning(f" Multiple skills detected in command: {unique_skills}")

    # 使用第一个检测到的技能名称
    detected_skill_name = skill_names[0]

    # 重写路径：将 .claude/skills/{name}/ 替换为空
    rewritten = command
    for match in matches:
        skill_name = match.group(1)
        pattern = f".claude/skills/{skill_name}/"
        rewritten = rewritten.replace(pattern, "")

    if rewritten != command:
        logger.warning(f" 路径重写: .claude/skills/{detected_skill_name}/ -> (相对路径)")
        logger.warning(f" 原始: {command}")
        logger.warning(f" 重写: {rewritten}")

    return rewritten, detected_skill_name


def prepare_skill_env(workspace_root: Path, skill_storage_path: str, skill_name: str | None = None) -> dict[str, str]:
    """准备技能执行环境

    Args:
        workspace_root: 工作空间根目录
        skill_storage_path: 技能存储路径（如 /path/to/skills/prebuilt/web_artifacts_builder）
        skill_name: 技能名称（可选，用于精确定位）

    Returns:
        环境变量字典（包含 PYTHONPATH 和工作目录）
    """
    # 从存储路径提取技能名称（如果未提供）
    if not skill_name:
        skill_name = extract_skill_name(skill_storage_path)

    # 技能在工作空间中的路径
    skill_workspace_path = workspace_root / "skills" / skill_name

    # 设置 PYTHONPATH（添加技能根目录，支持 from scripts.xxx import）
    pythonpath = str(skill_workspace_path)

    # 设置工作目录到技能根目录
    working_dir = str(skill_workspace_path)

    logger.warning(f" 准备技能环境: {skill_name}")
    logger.warning(f" PYTHONPATH: {pythonpath}")
    logger.warning(f" 工作目录: {working_dir}")

    return {"PYTHONPATH": pythonpath, "working_dir": working_dir}


def detect_skill_script_command(command: str) -> tuple[bool, str | None]:
    """检测命令中是否涉及技能脚本

    Args:
        command: Bash 命令

    Returns:
        元组 (是否涉及技能脚本, 技能名称或None)
    """
    # 检测 .claude/skills/{name}/ 路径
    match = re.search(CLAUDE_SKILL_PATH_PATTERN, command)
    if match:
        skill_name = match.group(1)
        logger.warning(f" 检测到技能脚本，设置工作目录: {skill_name}")
        return True, skill_name

    return False, None


def resolve_skill_env(
    skill_name: str, primary_env: str | None, skill_env_config: dict[str, str] | None
) -> dict[str, str]:
    """Resolve environment variables for a skill execution.

    Merges per-skill env config with apiKey→primaryEnv auto-mapping.
    This is a pure function — no state, no side effects.

    Args:
        skill_name: Skill name (for logging).
        primary_env: The env var name declared in SKILL.md frontmatter
            (e.g. "BRAVE_API_KEY"). When set, api_key auto-maps to it.
        skill_env_config: Per-skill env config from user settings.
            Keys are env var names, values are env var values.
            Special key "api_key" triggers primaryEnv mapping.

    Returns:
        Resolved env vars dict ready for injection into ExecutionContext.env.
    """
    if not skill_env_config:
        return {}

    env: dict[str, str] = {}

    api_key = skill_env_config.get("api_key")

    for key, value in skill_env_config.items():
        if key == "api_key":
            continue
        if value:
            env[key] = value

    if api_key and primary_env:
        env[primary_env] = api_key

    if env:
        logger.info("Skill env resolved for '%s': %s", skill_name, list(env.keys()))

    return env
