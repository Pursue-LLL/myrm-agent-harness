from __future__ import annotations

from myrm_agent_harness.toolkits.artifacts.controller import (
    ProgressiveLayerRenderController,
)
from myrm_agent_harness.toolkits.artifacts.device_memory import (
    DeviceStateCommandMemory,
)
from myrm_agent_harness.toolkits.artifacts.models import (
    BoundingBox2D,
    CADLayer,
    DeviceCommandEntry,
    DeviceProtocolType,
    DeviceStateSnapshot,
    LODLevel,
    Point2D,
    VectorPrimitive,
    VectorPrimitiveType,
)
from myrm_agent_harness.toolkits.artifacts.simplifier import (
    DouglasPeuckerSimplifier,
    EdgeSharpener,
)


def test_bounding_box_and_points() -> None:
    pt1 = Point2D(x=0.0, y=0.0)
    pt2 = Point2D(x=3.0, y=4.0)
    assert pt1.distance_to(pt2) == 5.0

    bbox = BoundingBox2D(min_x=0.0, min_y=0.0, max_x=10.0, max_y=10.0)
    assert bbox.width == 10.0
    assert bbox.height == 10.0
    assert bbox.diagonal > 14.14
    assert bbox.contains_point(Point2D(x=5.0, y=5.0)) is True
    assert bbox.contains_point(Point2D(x=15.0, y=5.0)) is False

    bbox_intersect = BoundingBox2D(min_x=5.0, min_y=5.0, max_x=15.0, max_y=15.0)
    assert bbox.intersects(bbox_intersect) is True

    bbox_disjoint = BoundingBox2D(min_x=20.0, min_y=20.0, max_x=30.0, max_y=30.0)
    assert bbox.intersects(bbox_disjoint) is False


def test_douglas_peucker_polyline_simplification() -> None:
    # 构造一条长基线，中间有 50 个微小扰动点（扰动幅度 < 0.1）
    pts: list[Point2D] = [Point2D(x=0.0, y=0.0)]
    for i in range(1, 51):
        noise = 0.05 if i % 2 == 0 else -0.05
        pts.append(Point2D(x=float(i), y=noise))
    pts.append(Point2D(x=52.0, y=0.0))

    # epsilon 设置为 0.2，所有中间扰动点应被完全削减
    simplified = DouglasPeuckerSimplifier.simplify_polyline(pts, epsilon=0.2)
    assert len(simplified) == 2
    assert simplified[0] == pts[0]
    assert simplified[-1] == pts[-1]


def test_douglas_peucker_polygon_simplification() -> None:
    # 构造一个闭合多边形：正方形并在每条边上加细微噪声点
    points: list[Point2D] = [
        Point2D(x=0.0, y=0.0),
        Point2D(x=5.0, y=0.01),
        Point2D(x=10.0, y=0.0),
        Point2D(x=10.0, y=5.02),
        Point2D(x=10.0, y=10.0),
        Point2D(x=5.0, y=9.98),
        Point2D(x=0.0, y=10.0),
        Point2D(x=0.0, y=4.99),
        Point2D(x=0.0, y=0.0),
    ]

    simplified = DouglasPeuckerSimplifier.simplify_polygon(points, epsilon=0.1)
    # 首尾应保持闭合
    assert simplified[0].x == simplified[-1].x
    assert simplified[0].y == simplified[-1].y
    assert len(simplified) < len(points)


def test_edge_sharpener_corner_preservation() -> None:
    # 直角弯折走线：(0,0) -> (10,0) -> (10,10)，在拐角附近有微小波动
    points: list[Point2D] = [
        Point2D(x=0.0, y=0.0),
        Point2D(x=5.0, y=0.02),
        Point2D(x=10.0, y=0.0),  # 90度直角拐点
        Point2D(x=10.0, y=5.01),
        Point2D(x=10.0, y=10.0),
    ]

    # 角点锚定简化
    sharp_simplified = EdgeSharpener.simplify_with_corner_preservation(
        points, epsilon=0.1, max_angle_degrees=100.0
    )
    # 直角拐点 (10, 0) 必须保留在结果中
    corner_present = any(p.x == 10.0 and p.y == 0.0 for p in sharp_simplified)
    assert corner_present is True
    assert len(sharp_simplified) == 3


def test_adaptive_epsilon_computation() -> None:
    bbox = BoundingBox2D(min_x=0.0, min_y=0.0, max_x=100.0, max_y=100.0)
    eps0 = DouglasPeuckerSimplifier.compute_adaptive_epsilon(
        bbox, LODLevel.LOD0_ORIGINAL
    )
    eps1 = DouglasPeuckerSimplifier.compute_adaptive_epsilon(
        bbox, LODLevel.LOD1_SIMPLIFIED
    )
    eps2 = DouglasPeuckerSimplifier.compute_adaptive_epsilon(
        bbox, LODLevel.LOD2_OVERVIEW
    )

    assert eps0 == 0.0
    assert eps1 > 0.0
    assert eps2 > eps1


def test_progressive_layer_render_controller_scheduling() -> None:
    controller = ProgressiveLayerRenderController()

    layer_outline = CADLayer(
        layer_id="layer_outline",
        display_name="Board Outline",
        z_index=10,
        is_critical_core=True,
    )
    layer_silkscreen = CADLayer(
        layer_id="layer_silk",
        display_name="Silkscreen",
        z_index=1,
        is_critical_core=False,
    )

    prim1 = VectorPrimitive(
        id="prim_1",
        primitive_type=VectorPrimitiveType.POLYLINE,
        points=[Point2D(x=0.0, y=0.0), Point2D(x=10.0, y=10.0)],
        layer_name="layer_outline",
    )
    prim2 = VectorPrimitive(
        id="prim_2",
        primitive_type=VectorPrimitiveType.POLYLINE,
        points=[Point2D(x=1.0, y=1.0), Point2D(x=2.0, y=2.0)],
        layer_name="layer_silk",
    )

    chunks = controller.generate_progressive_chunks(
        primitives=[prim2, prim1],  # 故意乱序输入
        layers=[layer_silkscreen, layer_outline],
        target_lod=LODLevel.LOD1_SIMPLIFIED,
        chunk_size=10,
    )

    assert len(chunks) == 2
    # 核心层 layer_outline 必须排在首位
    assert chunks[0].layer_id == "layer_outline"
    assert chunks[1].layer_id == "layer_silk"
    assert chunks[-1].is_final_chunk is True


def test_controller_generation_and_viewport_culling() -> None:
    controller = ProgressiveLayerRenderController()
    gen1 = controller.current_generation
    assert controller.is_generation_valid(gen1) is True

    gen2 = controller.invalidate()
    assert gen2 == gen1 + 1
    assert controller.is_generation_valid(gen1) is False
    assert controller.is_generation_valid(gen2) is True

    # 视口裁剪测试
    viewport = BoundingBox2D(min_x=0.0, min_y=0.0, max_x=50.0, max_y=50.0)
    in_prim = VectorPrimitive(
        id="prim_in",
        primitive_type=VectorPrimitiveType.POLYLINE,
        points=[Point2D(x=10.0, y=10.0), Point2D(x=20.0, y=20.0)],
        layer_name="layer_test",
    )
    out_prim = VectorPrimitive(
        id="prim_out",
        primitive_type=VectorPrimitiveType.POLYLINE,
        points=[Point2D(x=100.0, y=100.0), Point2D(x=110.0, y=110.0)],
        layer_name="layer_test",
    )

    culled = controller.cull_primitives_by_viewport(
        [in_prim, out_prim], viewport
    )
    assert len(culled) == 1
    assert culled[0].id == "prim_in"


def test_device_state_command_memory_lifecycle() -> None:
    memory = DeviceStateCommandMemory(trace_limit=10)

    # 1. 注册初始快照
    snap1 = DeviceStateSnapshot(
        snapshot_id="snap_001",
        device_id="mcu_esp32_01",
        protocol=DeviceProtocolType.UART_SERIAL,
        registers={"BAUDRATE": 115200, "BOOT_MODE": "NORMAL"},
        pin_states={"GPIO_2": True, "GPIO_4": False},
        timestamp_ns=1000000,
    )
    memory.record_snapshot(snap1)
    assert memory.get_latest_snapshot("mcu_esp32_01") == snap1

    # 2. 追加有序指令
    cmd1 = DeviceCommandEntry(
        command_id="cmd_001",
        device_id="mcu_esp32_01",
        protocol=DeviceProtocolType.UART_SERIAL,
        opcode="SET_PIN",
        payload_hex="0201",
        timestamp_ns=2000000,
    )
    assert memory.append_command(cmd1) is True
    assert memory.commit_command("mcu_esp32_01", "cmd_001", "ACK") is True

    # 3. 幂等性：已 committed 的指令重复追加应被拒绝
    assert memory.append_command(cmd1) is False

    # 4. 时序乱序：时间戳倒置的指令应被拒绝
    cmd_stale = DeviceCommandEntry(
        command_id="cmd_002",
        device_id="mcu_esp32_01",
        protocol=DeviceProtocolType.UART_SERIAL,
        opcode="READ_PIN",
        payload_hex="04",
        timestamp_ns=1500000,  # 小于 2000000
    )
    assert memory.append_command(cmd_stale) is False

    # 5. 状态回滚测试
    snap2 = DeviceStateSnapshot(
        snapshot_id="snap_002",
        device_id="mcu_esp32_01",
        protocol=DeviceProtocolType.UART_SERIAL,
        registers={"BAUDRATE": 9600},
        pin_states={"GPIO_2": False},
        timestamp_ns=3000000,
    )
    memory.record_snapshot(snap2)
    assert (
        memory.get_latest_snapshot("mcu_esp32_01").registers["BAUDRATE"] == 9600
    )

    # 回滚到 snap_001
    assert memory.rollback_to_snapshot("mcu_esp32_01", "snap_001") is True
    assert (
        memory.get_latest_snapshot("mcu_esp32_01").registers["BAUDRATE"]
        == 115200
    )
