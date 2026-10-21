"""eval_cases <-> evals.json 序列化/校验原语

技能 ZIP 包内回归门禁快照载体。导出时把 evolution SkillStore 中的
``SkillRecord.eval_cases`` 序列化为包内 ``evals.json``，导入时校验并还原，
保证技能跨实例迁移后回归门禁不丢失（与 agentskills evals 生态语义对齐）。

[INPUT]
- (none)

[OUTPUT]
- EVALS_FILE: str — 包内保留文件名
- EVALS_SCHEMA_VERSION: int — 当前 schema 版本
- serialize_eval_cases: (skill_name, eval_cases) -> str
- parse_evals_json: (content) -> list[dict] | None
- is_evals_file: (file_path) -> bool

[POS]
packaging 域：eval_cases ↔ evals.json 的纯序列化/校验原语，不依赖 evolution
存储实现，供 server 导出/导入侧复用。
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

EVALS_FILE = "evals.json"
EVALS_SCHEMA_VERSION = 1


def is_evals_file(file_path: str) -> bool:
    """判断是否为包内保留名 evals.json（顶层或任意层级）。"""
    return file_path == EVALS_FILE or file_path.endswith(f"/{EVALS_FILE}")


def serialize_eval_cases(skill_name: str, eval_cases: list[dict]) -> str:
    """序列化 eval_cases 为 evals.json 内容。

    Args:
        skill_name: 技能名，写入包内元数据便于审计
        eval_cases: SkillRecord.eval_cases 原始结构（list[dict]）

    Returns:
        evals.json 字符串内容
    """
    payload = {
        "schema_version": EVALS_SCHEMA_VERSION,
        "skill_name": skill_name,
        "evals": eval_cases,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def parse_evals_json(content: str | bytes) -> list[dict] | None:
    """解析并校验 evals.json 内容。

    Args:
        content: evals.json 原始内容（bytes 或 str）

    Returns:
        校验通过的 eval_cases 列表；格式非法或 schema 不兼容时返回 None
    """
    try:
        if isinstance(content, bytes):
            text = content.decode("utf-8")
        else:
            text = content
        payload = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("Invalid evals.json payload: %s", exc)
        return None

    if not isinstance(payload, dict):
        return None

    schema_version = payload.get("schema_version")
    if schema_version != EVALS_SCHEMA_VERSION:
        logger.warning(
            "Unsupported evals.json schema_version=%r (expected %d)",
            schema_version,
            EVALS_SCHEMA_VERSION,
        )
        return None

    evals = payload.get("evals")
    if not isinstance(evals, list):
        return None

    if not all(isinstance(item, dict) for item in evals):
        logger.warning("evals.json contains non-object eval case entries")
        return None

    return evals
