"""Public facade of the artifacts subsystem.

[INPUT]
- toolkits.artifacts.controller::ProgressiveLayerRenderController (POS: Progressive layer-wise streaming
  render controller with generation invalidation.)
- toolkits.artifacts.device_memory::DeviceStateCommandMemory (POS: Multi-protocol hardware device state
  snapshot and command sequence memory.)
- toolkits.artifacts.models::BoundingBox2D, CADLayer, DeviceCommandEntry, DeviceProtocolType,
  DeviceStateSnapshot, LODLevel, Point2D, ProgressiveRenderChunk, +2 more (POS: Typed CAD vector-geometry
  contracts (2D points, bounding boxes, vector primitives, LOD levels, layers, progressive render chunks)
  for the artifacts toolkit.)
- toolkits.artifacts.simplifier::DouglasPeuckerSimplifier, EdgeSharpener (POS: High-performance 2D geometric
  simplification operator.)

[OUTPUT]
- Package facade re-exporting 14 public names: BoundingBox2D, CADLayer, DeviceCommandEntry,
  DeviceProtocolType, DeviceStateCommandMemory, DeviceStateSnapshot, DouglasPeuckerSimplifier,
  EdgeSharpener, LODLevel, Point2D, ProgressiveLayerRenderController, ProgressiveRenderChunk,
  VectorPrimitive, VectorPrimitiveType

[POS]
Public facade of the artifacts subsystem.
"""

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
    ProgressiveRenderChunk,
    VectorPrimitive,
    VectorPrimitiveType,
)
from myrm_agent_harness.toolkits.artifacts.simplifier import (
    DouglasPeuckerSimplifier,
    EdgeSharpener,
)

__all__ = [
    "BoundingBox2D",
    "CADLayer",
    "DeviceCommandEntry",
    "DeviceProtocolType",
    "DeviceStateCommandMemory",
    "DeviceStateSnapshot",
    "DouglasPeuckerSimplifier",
    "EdgeSharpener",
    "LODLevel",
    "Point2D",
    "ProgressiveLayerRenderController",
    "ProgressiveRenderChunk",
    "VectorPrimitive",
    "VectorPrimitiveType",
]
