"""技能执行命令路径工具

[INPUT]
- re::re (POS: 正则表达式库)

[OUTPUT]
- rewrite_skill_paths(): 重写代码中的硬编码技能路径
- detect_skill_script_command(): 检测命令中是否涉及技能脚本

[POS]
Skill command path utilities for bash execution. Skill env injection and
execution env prep live in `agent.meta_tools.bash` (skill_env_map) and
`toolkits.code_execution` (PTC system) respectively.

"""

import logging
import re

logger = logging.getLogger(__name__)

# Claude 标准技能目录模式
CLAUDE_SKILL_PATH_PATTERN = r"\.claude/skills/([^/\s]+)/"


def rewrite_skill_paths(command: str) -> tuple[str, str | None]:
    """重写命令中的技能路径为相对路径

    将硬编码的技能路径（如 .claude/skills/ui-ux-pro-max/scripts/xxx.py）
    转换为相对路径（如 scripts/xxx.py），配合工作目录设置使用。

    支持的转换模式：
    - .claude/skills/{name}/xxx -> xxx
    - python3 .claude/skills/{name}/scripts/xxx.py -> python3 scripts/xxx.py

    Args:
        command: 原始命令

    Returns:
        元组 (重写后的命令, 检测到的技能名称或None)
        技能名称可用于后续精确设置工作目录
    """
    matches = list(re.finditer(CLAUDE_SKILL_PATH_PATTERN, command))
    if not matches:
        return command, None

    # 提取所有技能名称
    skill_names = [m.group(1) for m in matches]

    # 多个不同技能属于异常输入，保留 warning 提示
    unique_skills = set(skill_names)
    if len(unique_skills) > 1:
        logger.warning("Multiple skills detected in command: %s", unique_skills)

    # 使用第一个检测到的技能名称
    detected_skill_name = skill_names[0]

    # 重写路径：将 .claude/skills/{name}/ 替换为空
    rewritten = command
    for match in matches:
        skill_name = match.group(1)
        pattern = f".claude/skills/{skill_name}/"
        rewritten = rewritten.replace(pattern, "")

    if rewritten != command:
        logger.debug(
            "Rewrote skill path .claude/skills/%s/ to relative", detected_skill_name
        )

    return rewritten, detected_skill_name


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
        logger.info("Detected skill script, setting working directory: %s", skill_name)
        return True, skill_name

    return False, None
