"""智能体能力纪元轻量指纹算法模块。

提取影响模型推理的 6 大静态核心能力要素，执行字节级规范化序列化哈希，
生成格式为 'ep-{8位sha256}' 的权威能力纪元戳，杜绝动态时间戳噪声与隐蔽要素漏检。

[INPUT]
- __future__
- dataclasses
- hashlib
- json
- typing

[OUTPUT]
- CanonicalCapabilityManifest
- CapabilityEpochHasher

[POS]
智能体能力纪元轻量指纹算法模块。
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Dict, Optional, Tuple


@dataclass(frozen=True, slots=True)
class CanonicalCapabilityManifest:
    """智能体静态能力全要素清单。

    严格覆盖影响大模型推理行为的静态核心维度，杜绝隐蔽漏判；
    严禁包含时间戳、自增ID等瞬态字段，确保哈希纯净幂等。
    """

    system_prompt: str
    skills: Tuple[str, ...] = ()
    tools: Tuple[str, ...] = ()
    mcp_servers: Tuple[str, ...] = ()
    model_id: str = "default_model"
    reasoning_effort: Optional[str] = None
    temperature: float = 0.7
    soul_content: Optional[str] = None


class CapabilityEpochHasher:
    """智能体能力纪元哈希计算器。"""

    @staticmethod
    def normalize_text(text: Optional[str]) -> str:
        """统一换行符并去除首尾空白，消除多端文本格式歧义。"""
        if not text:
            return ""
        return text.replace("\r\n", "\n").replace("\r", "\n").strip()

    @classmethod
    def calculate_epoch(cls, manifest: CanonicalCapabilityManifest) -> str:
        """计算给定能力清单的权威能力纪元戳 (Capability Epoch)。

        格式：'ep-{8位小写十六进制SHA-256}'。
        """
        # 构建规范化排序字典
        payload: Dict[str, object] = {
            "system_prompt": cls.normalize_text(manifest.system_prompt),
            "skills": sorted(manifest.skills),
            "tools": sorted(manifest.tools),
            "mcp_servers": sorted(manifest.mcp_servers),
            "model_id": manifest.model_id.strip(),
            "reasoning_effort": manifest.reasoning_effort.strip() if manifest.reasoning_effort else None,
            "temperature": round(float(manifest.temperature), 3),
            "soul_content": cls.normalize_text(manifest.soul_content),
        }

        # 字节级无歧义序列化：键排序、紧凑分隔符、UTF-8 编码
        serialized_bytes = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        digest_hex = hashlib.sha256(serialized_bytes).hexdigest()[:8]
        return f"ep-{digest_hex}"
