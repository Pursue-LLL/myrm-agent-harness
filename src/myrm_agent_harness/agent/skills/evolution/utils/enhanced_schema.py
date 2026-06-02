"""@input: None
@output: 预定义陷阱和验证模板（零 LLM 成本）
@pos: 技能系统 / 预定义模板库

预定义模板库（Pre-defined Templates）。

核心价值：
- 零 LLM 成本的踩坑警示
- 零 LLM 成本的验证方式参考
- 复用历史经验，降低技能失败率

设计原则：
- 只保留预定义模板，删除未被实际消费的结构化类型定义
- 模板可直接引用，无需实例化 dataclass

[INPUT]
- (none)

[OUTPUT]
- SkillTrap: COMMON_TRAPS templates are consumed by _match_common_trap...
- VerificationStep: class — Verification Step
- get_trap_description: Args:
- get_verification_description: Args:

[POS]
@input: None
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SkillTrap:
    """技能潜在陷阱。

    记录执行过程中可能遇到的问题和解决方案。
    COMMON_TRAPS templates are consumed by _match_common_traps() for CAPTURED skills.
    """

    description: str  # 陷阱描述
    severity: str  # 严重程度: "low", "medium", "high", "critical"
    trigger_condition: str  # 触发条件
    mitigation: str  # 缓解方案
    discovered_at: datetime | None = None  # 发现时间
    occurrence_count: int = 0  # 出现次数


@dataclass
class VerificationStep:
    """技能验证步骤。

    定义如何确认技能执行成功。
    """

    step_id: str  # 步骤标识
    description: str  # 验证描述
    expected_output: str  # 期望输出
    validation_method: str  # 验证方法: "output_check", "file_exists", "command_success", "api_response"
    is_required: bool = True  # 是否必须通过
    timeout_seconds: float = 30.0  # 超时时间


# 预定义的常见陷阱模板（零 LLM 成本）
# 这些模板可直接在技能文档中引用，无需 LLM 生成
COMMON_TRAPS: dict[str, SkillTrap] = {
    "npm_install_timeout": SkillTrap(
        description="npm install 可能因网络问题超时",
        severity="medium",
        trigger_condition="执行 npm install 且网络不稳定",
        mitigation="使用 --registry 参数指定国内镜像源，或增加 timeout 配置",
    ),
    "api_rate_limit": SkillTrap(
        description="API 调用可能触发速率限制",
        severity="high",
        trigger_condition="连续高频调用 API",
        mitigation="添加速率限制处理和重试逻辑",
    ),
    "file_permission_denied": SkillTrap(
        description="文件操作可能因权限不足失败",
        severity="medium",
        trigger_condition="写入系统目录或受保护文件",
        mitigation="检查权限，使用 sudo 或切换目录",
    ),
    "memory_overflow": SkillTrap(
        description="处理大数据时内存溢出",
        severity="high",
        trigger_condition="处理超过 100MB 的数据",
        mitigation="使用分块处理或流式读取",
    ),
    "encoding_mismatch": SkillTrap(
        description="文件编码不一致导致解析失败",
        severity="medium",
        trigger_condition="处理包含中文或特殊字符的文件",
        mitigation="显式指定 encoding='utf-8'",
    ),
    "python_version_incompatible": SkillTrap(
        description="Python 版本不兼容",
        severity="high",
        trigger_condition="使用 Python 3.10+ 特性在旧版本运行",
        mitigation="检查版本并使用兼容语法",
    ),
    "docker_container_not_found": SkillTrap(
        description="Docker 容器不存在或未启动",
        severity="high",
        trigger_condition="依赖特定 Docker 容器执行",
        mitigation="检查容器状态，添加 docker ps 验证",
    ),
    "git_branch_conflict": SkillTrap(
        description="Git 分支冲突导致合并失败",
        severity="medium",
        trigger_condition="合并分支时有未解决的冲突",
        mitigation="先处理冲突，再执行合并",
    ),
}


# 预定义的验证步骤模板（零 LLM 成本）
# 这些模板可直接在技能文档中引用，无需 LLM 生成
COMMON_VERIFICATIONS: dict[str, VerificationStep] = {
    "output_non_empty": VerificationStep(
        step_id="output_check",
        description="检查输出不为空",
        expected_output="非空字符串或对象",
        validation_method="output_check",
        is_required=True,
    ),
    "file_created": VerificationStep(
        step_id="file_exists",
        description="检查目标文件已创建",
        expected_output="文件存在",
        validation_method="file_exists",
        is_required=True,
    ),
    "command_success": VerificationStep(
        step_id="cmd_success",
        description="检查命令执行成功",
        expected_output="exit_code == 0",
        validation_method="command_success",
        is_required=True,
    ),
    "no_errors": VerificationStep(
        step_id="error_check",
        description="检查无错误日志",
        expected_output="ERROR 级别日志数为 0",
        validation_method="output_check",
        is_required=False,
    ),
    "api_response_ok": VerificationStep(
        step_id="api_check",
        description="检查 API 返回成功状态",
        expected_output="status_code == 200",
        validation_method="api_response",
        is_required=True,
    ),
    "git_push_success": VerificationStep(
        step_id="git_check",
        description="检查 Git push 成功",
        expected_output="无 rejected 或冲突提示",
        validation_method="command_success",
        is_required=True,
    ),
}


def get_trap_description(trap_key: str) -> str:
    """获取陷阱描述文本（用于技能文档生成）。

    Args:
        trap_key: 陷阱键名

    Returns:
        格式化的陷阱描述文本
    """
    trap = COMMON_TRAPS.get(trap_key)
    if not trap:
        return ""

    severity_icon = {
        "low": "",
        "medium": "",
        "high": "",
        "critical": "",
    }.get(trap.severity, "")

    return f"{severity_icon} {trap.description}: 触发条件={trap.trigger_condition}, 解决方案={trap.mitigation}"


def get_verification_description(verification_key: str) -> str:
    """获取验证描述文本（用于技能文档生成）。

    Args:
        verification_key: 验证键名

    Returns:
        格式化的验证描述文本
    """
    verification = COMMON_VERIFICATIONS.get(verification_key)
    if not verification:
        return ""

    required_icon = ""
    return f"{required_icon} {verification.description}: 方法={verification.validation_method}, 期望={verification.expected_output}"


__all__ = [
    "COMMON_TRAPS",
    "COMMON_VERIFICATIONS",
    "SkillTrap",
    "VerificationStep",
    "get_trap_description",
    "get_verification_description",
]
