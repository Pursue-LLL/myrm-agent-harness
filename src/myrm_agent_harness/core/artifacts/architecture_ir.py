"""Architecture Structured JSON IR Contract and Pre-delivery Validator.

[INPUT]
- pydantic::BaseModel, Field
- enum::StrEnum
- json

[OUTPUT]
- DiagramType: enum — 支持的 5 大系统图谱类型
- ArchitectureNodeType: enum — 语义化节点分类
- ArchitectureNode: class — 拓扑节点
- ArchitectureEdge: class — 拓扑连线
- ArchitectureGroup: class — 逻辑架构分组
- ArchitectureIR: class — 标准 JSON IR 全量模型
- ValidationReceipt: class — 交付前静态校验与自愈收据
- validate_and_sanitize_architecture_ir: function — 拓扑校验自愈门禁

[POS]
Harness Core Layer — 语义与几何彻底解耦的架构图标准数据模型与合规校验器。
"""

from __future__ import annotations

import json
from enum import StrEnum
from pydantic import BaseModel, Field


class DiagramType(StrEnum):
    """支持的标准技术图谱分类"""

    ARCHITECTURE = "architecture"
    WORKFLOW = "workflow"
    SEQUENCE = "sequence"
    DATAFLOW = "dataflow"
    LIFECYCLE = "lifecycle"


class ArchitectureNodeType(StrEnum):
    """标准化语义节点类型（映射对应视觉调色板与 Icon）"""

    FRONTEND = "frontend"
    BACKEND = "backend"
    DATABASE = "database"
    CLOUD = "cloud"
    SECURITY = "security"
    MESSAGEBUS = "messagebus"
    EXTERNAL = "external"
    CACHE = "cache"
    GATEWAY = "gateway"
    SERVICE = "service"


class ArchitectureNode(BaseModel):
    """拓扑节点定义"""

    id: str = Field(description="全局唯一、语义稳定的组件标识符，例如: api-gateway")
    label: str = Field(description="节点展示名称，例如: API Gateway")
    type: str = Field(
        default="service", description="组件类别，对齐 ArchitectureNodeType"
    )
    group_id: str | None = Field(default=None, description="所属分组边界 ID")
    tech_stack: str | None = Field(
        default=None, description="技术栈标签，例如: FastAPI / Redis"
    )
    description: str = Field(default="", description="组件简要功能说明")
    status: str = Field(
        default="normal", description="状态标记: normal | new | deprecated | modified"
    )


class ArchitectureEdge(BaseModel):
    """拓扑连接关系定义"""

    source: str = Field(description="源节点 ID")
    target: str = Field(description="目标节点 ID")
    label: str = Field(default="", description="连线语义说明，例如: 校验 Token")
    protocol: str = Field(default="", description="通信协议，例如: HTTPS / gRPC / AMQP")
    animated: bool = Field(default=False, description="是否渲染流光动画")
    style: str = Field(default="solid", description="线条样式: solid | dashed")


class ArchitectureGroup(BaseModel):
    """逻辑架构分组边界"""

    id: str = Field(description="分组唯一标识符，例如: dmz-network")
    label: str = Field(description="分组边界名称，例如: DMZ 隔离区")
    color: str | None = Field(default=None, description="可选边界高亮色彩")


class ArchitectureIR(BaseModel):
    """标准架构图 JSON IR 数据模型"""

    title: str = Field(description="架构图标题")
    diagram_type: DiagramType = Field(
        default=DiagramType.ARCHITECTURE, description="图谱类型"
    )
    version: str = Field(default="1.0.0", description="语义版本号")
    description: str = Field(default="", description="架构设计背景与摘要")
    nodes: list[ArchitectureNode] = Field(default_factory=list, description="节点清单")
    edges: list[ArchitectureEdge] = Field(
        default_factory=list, description="连线关系清单"
    )
    groups: list[ArchitectureGroup] = Field(
        default_factory=list, description="分组清单"
    )
    metadata: dict[str, str] = Field(default_factory=dict, description="额外扩展元数据")


class ValidationReceipt(BaseModel):
    """交付前静态合规性校验与自愈收据"""

    is_valid: bool = Field(description="是否通过校验门禁")
    node_count: int = Field(description="有效节点总数")
    edge_count: int = Field(description="有效连线总数")
    sanitized_dangling_edges: int = Field(
        default=0, description="自动修剪的悬空非法边数量"
    )
    isolated_nodes: list[str] = Field(
        default_factory=list, description="孤立未连接节点清单"
    )
    errors: list[str] = Field(default_factory=list, description="阻断性错误列表")
    warnings: list[str] = Field(default_factory=list, description="温和预警与提示信息")


def validate_and_sanitize_architecture_ir(
    raw_input: str | dict[str, object],
) -> tuple[ArchitectureIR | None, ValidationReceipt]:
    """验证并清洗架构拓扑 JSON IR，执行悬空边自愈，确保绝对可渲染。"""
    errors: list[str] = []
    warnings: list[str] = []

    parsed_dict: dict[str, object]
    if isinstance(raw_input, str):
        try:
            parsed_dict = json.loads(raw_input)
            if not isinstance(parsed_dict, dict):
                return None, ValidationReceipt(
                    is_valid=False,
                    node_count=0,
                    edge_count=0,
                    errors=["Raw input must be a JSON object, got non-dict root"],
                )
        except json.JSONDecodeError as err:
            return None, ValidationReceipt(
                is_valid=False,
                node_count=0,
                edge_count=0,
                errors=[f"Invalid JSON syntax: {err}"],
            )
    else:
        parsed_dict = raw_input

    try:
        ir_model = ArchitectureIR.model_validate(parsed_dict)
    except Exception as err:
        return None, ValidationReceipt(
            is_valid=False,
            node_count=0,
            edge_count=0,
            errors=[f"Schema validation failed: {err}"],
        )

    # 1. 校验 Node ID 唯一性与清洗
    seen_ids: set[str] = set()
    unique_nodes: list[ArchitectureNode] = []
    for node in ir_model.nodes:
        clean_id = node.id.strip()
        if not clean_id:
            warnings.append("Skipped node with empty id")
            continue
        if clean_id in seen_ids:
            warnings.append(f"Duplicate node ID detected and deduplicated: {clean_id}")
            continue
        seen_ids.add(clean_id)
        node.id = clean_id
        if not node.label.strip():
            node.label = clean_id
        unique_nodes.append(node)

    ir_model.nodes = unique_nodes

    # 2. 校验连线合法性，剔除悬空边 (Dangling Edges)
    valid_edges: list[ArchitectureEdge] = []
    sanitized_dangling = 0
    connected_node_ids: set[str] = set()

    for edge in ir_model.edges:
        src = edge.source.strip()
        tgt = edge.target.strip()
        if src not in seen_ids or tgt not in seen_ids:
            sanitized_dangling += 1
            warnings.append(
                f"Dangling edge removed: {src} -> {tgt} (one or both nodes missing)"
            )
            continue
        edge.source = src
        edge.target = tgt
        connected_node_ids.add(src)
        connected_node_ids.add(tgt)
        valid_edges.append(edge)

    ir_model.edges = valid_edges

    # 3. 统计孤立节点 (度数为 0)
    isolated: list[str] = [nid for nid in seen_ids if nid not in connected_node_ids]
    if isolated:
        warnings.append(f"Isolated nodes found: {', '.join(isolated)}")

    receipt = ValidationReceipt(
        is_valid=len(unique_nodes) > 0,
        node_count=len(unique_nodes),
        edge_count=len(valid_edges),
        sanitized_dangling_edges=sanitized_dangling,
        isolated_nodes=isolated,
        errors=errors,
        warnings=warnings,
    )

    if not receipt.is_valid:
        receipt.errors.append("Architecture IR contains zero valid nodes")

    return ir_model, receipt
