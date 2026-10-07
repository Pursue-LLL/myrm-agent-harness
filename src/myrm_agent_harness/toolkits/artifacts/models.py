"""Typed CAD vector-geometry contracts (2D points, bounding boxes, vector primitives, LOD levels, layers, progressive render chunks) for the artifacts toolkit.

[INPUT]
- External: pydantic

[OUTPUT]
- Point2D: Data model (fields: x, y)
- BoundingBox2D: Data model (fields: min_x, min_y, max_x, max_y)
- VectorPrimitiveType: Enum members: POLYLINE, POLYGON, ARC, VIA, PAD
- VectorPrimitive: Data model (fields: id, primitive_type, points, layer_name, stroke_width, fill_color,
  properties)
- LODLevel: Enum members: LOD0_ORIGINAL, LOD1_SIMPLIFIED, LOD2_OVERVIEW
- CADLayer: Data model (fields: layer_id, display_name, z_index, is_critical_core, color_hex, opacity)
- ProgressiveRenderChunk: Data model (fields: chunk_id, generation_id, layer_id, lod_level, primitives,
  is_final_chunk, total_points_count)
- DeviceProtocolType: Enum members: UART_SERIAL, I2C, SPI, GPIO, BLE, VIRTUAL_BUS
- DeviceStateSnapshot: Data model (fields: snapshot_id, device_id, protocol, registers, pin_states,
  timestamp_ns, is_authoritative)
- DeviceCommandEntry: Data model (fields: command_id, device_id, protocol, opcode, payload_hex,
  expected_response_hex, actual_response_hex, timestamp_ns...)

[POS]
Typed CAD vector-geometry contracts (2D points, bounding boxes, vector primitives, LOD levels, layers,
progressive render chunks) for the artifacts toolkit.
"""

from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Point2D(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float
    y: float

    def distance_to(self, other: Point2D) -> float:
        dx = self.x - other.x
        dy = self.y - other.y
        return math.sqrt(dx * dx + dy * dy)


class BoundingBox2D(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return max(0.0, self.max_x - self.min_x)

    @property
    def height(self) -> float:
        return max(0.0, self.max_y - self.min_y)

    @property
    def diagonal(self) -> float:
        w = self.width
        h = self.height
        return math.sqrt(w * w + h * h)

    def contains_point(self, pt: Point2D) -> bool:
        return (
            self.min_x <= pt.x <= self.max_x
            and self.min_y <= pt.y <= self.max_y
        )

    def intersects(self, other: BoundingBox2D) -> bool:
        return not (
            self.max_x < other.min_x
            or self.min_x > other.max_x
            or self.max_y < other.min_y
            or self.min_y > other.max_y
        )


class VectorPrimitiveType(StrEnum):
    POLYLINE = "polyline"
    POLYGON = "polygon"
    ARC = "arc"
    VIA = "via"
    PAD = "pad"


class VectorPrimitive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    primitive_type: VectorPrimitiveType
    points: list[Point2D]
    layer_name: str
    stroke_width: float = 1.0
    fill_color: str | None = None
    properties: dict[str, str | int | float | bool] = Field(default_factory=dict)

    def calculate_bounding_box(self) -> BoundingBox2D:
        if not self.points:
            return BoundingBox2D(min_x=0.0, min_y=0.0, max_x=0.0, max_y=0.0)
        xs = [p.x for p in self.points]
        ys = [p.y for p in self.points]
        return BoundingBox2D(
            min_x=min(xs),
            min_y=min(ys),
            max_x=max(xs),
            max_y=max(ys),
        )


class LODLevel(StrEnum):
    LOD0_ORIGINAL = "lod0"
    LOD1_SIMPLIFIED = "lod1"
    LOD2_OVERVIEW = "lod2"


class CADLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer_id: str
    display_name: str
    z_index: int
    is_critical_core: bool = False
    color_hex: str = "#000000"
    opacity: float = 1.0


class ProgressiveRenderChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    generation_id: int
    layer_id: str
    lod_level: LODLevel
    primitives: list[VectorPrimitive]
    is_final_chunk: bool = False
    total_points_count: int = 0


class DeviceProtocolType(StrEnum):
    UART_SERIAL = "uart_serial"
    I2C = "i2c"
    SPI = "spi"
    GPIO = "gpio"
    BLE = "ble"
    VIRTUAL_BUS = "virtual_bus"


class DeviceStateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    device_id: str
    protocol: DeviceProtocolType
    registers: dict[str, int | float | str] = Field(default_factory=dict)
    pin_states: dict[str, bool] = Field(default_factory=dict)
    timestamp_ns: int
    is_authoritative: bool = True


class DeviceCommandEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str
    device_id: str
    protocol: DeviceProtocolType
    opcode: str
    payload_hex: str
    expected_response_hex: str | None = None
    actual_response_hex: str | None = None
    timestamp_ns: int
    is_committed: bool = False
