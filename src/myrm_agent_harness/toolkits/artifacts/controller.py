from __future__ import annotations

import uuid
from typing import Final

from myrm_agent_harness.toolkits.artifacts.models import (
    BoundingBox2D,
    CADLayer,
    LODLevel,
    ProgressiveRenderChunk,
    VectorPrimitive,
    VectorPrimitiveType,
)
from myrm_agent_harness.toolkits.artifacts.simplifier import (
    DouglasPeuckerSimplifier,
    EdgeSharpener,
)

DEFAULT_CHUNK_SIZE: Final[int] = 200


class ProgressiveLayerRenderController:
    """Progressive layer-wise streaming render controller with generation invalidation.

    Adapted from PCB_lightgraph progressiverendercontroller.cpp architecture to
    schedule multi-layer CAD vector artifacts progressively with viewport culling,
    LOD simplification, and stale generation cancellation.
    """

    def __init__(self) -> None:
        self._current_generation: int = 1

    @property
    def current_generation(self) -> int:
        return self._current_generation

    def invalidate(self) -> int:
        """Invalidate obsolete render jobs and advance generation counter."""
        self._current_generation += 1
        return self._current_generation

    def is_generation_valid(self, generation_id: int) -> bool:
        """Check whether the given generation matches the active counter."""
        return generation_id == self._current_generation

    @staticmethod
    def cull_primitives_by_viewport(
        primitives: list[VectorPrimitive],
        viewport: BoundingBox2D,
    ) -> list[VectorPrimitive]:
        """Cull out primitives completely outside the active viewport bounding box."""
        visible: list[VectorPrimitive] = []
        for prim in primitives:
            prim_bbox = prim.calculate_bounding_box()
            if prim_bbox.intersects(viewport):
                visible.append(prim)
        return visible

    @staticmethod
    def simplify_primitive(
        prim: VectorPrimitive,
        lod_level: LODLevel,
        overall_bbox: BoundingBox2D,
    ) -> VectorPrimitive:
        """Apply LOD simplification and corner preservation to a vector primitive."""
        if lod_level == LODLevel.LOD0_ORIGINAL or len(prim.points) <= 2:
            return prim

        epsilon = DouglasPeuckerSimplifier.compute_adaptive_epsilon(
            overall_bbox, lod_level
        )
        if epsilon <= 0.0:
            return prim

        if prim.primitive_type == VectorPrimitiveType.POLYGON:
            new_pts = DouglasPeuckerSimplifier.simplify_polygon(
                prim.points, epsilon
            )
        else:
            new_pts = EdgeSharpener.simplify_with_corner_preservation(
                prim.points, epsilon
            )

        return VectorPrimitive(
            id=prim.id,
            primitive_type=prim.primitive_type,
            points=new_pts,
            layer_name=prim.layer_name,
            stroke_width=prim.stroke_width,
            fill_color=prim.fill_color,
            properties=dict(prim.properties),
        )

    def generate_progressive_chunks(
        self,
        primitives: list[VectorPrimitive],
        layers: list[CADLayer],
        viewport: BoundingBox2D | None = None,
        target_lod: LODLevel = LODLevel.LOD1_SIMPLIFIED,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        generation_id: int | None = None,
    ) -> list[ProgressiveRenderChunk]:
        """Generate ordered progressive stream chunks prioritized by layer criticality."""
        active_gen = (
            generation_id
            if generation_id is not None
            else self._current_generation
        )

        sorted_layers = sorted(
            layers,
            key=lambda lyr: (not lyr.is_critical_core, lyr.z_index),
        )

        overall_min_x = min((p.x for prim in primitives for p in prim.points), default=0.0)
        overall_max_x = max((p.x for prim in primitives for p in prim.points), default=0.0)
        overall_min_y = min((p.y for prim in primitives for p in prim.points), default=0.0)
        overall_max_y = max((p.y for prim in primitives for p in prim.points), default=0.0)
        overall_bbox = BoundingBox2D(
            min_x=overall_min_x,
            min_y=overall_min_y,
            max_x=overall_max_x,
            max_y=overall_max_y,
        )

        chunks: list[ProgressiveRenderChunk] = []

        for lyr in sorted_layers:
            layer_prims = [p for p in primitives if p.layer_name == lyr.layer_id]
            if viewport is not None:
                layer_prims = self.cull_primitives_by_viewport(
                    layer_prims, viewport
                )

            simplified_prims = [
                self.simplify_primitive(p, target_lod, overall_bbox)
                for p in layer_prims
            ]

            if not simplified_prims:
                continue

            for i in range(0, len(simplified_prims), max(1, chunk_size)):
                batch = simplified_prims[i : i + chunk_size]
                pts_count = sum(len(p.points) for p in batch)
                chunk = ProgressiveRenderChunk(
                    chunk_id=f"chunk_{lyr.layer_id}_{active_gen}_{uuid.uuid4().hex[:8]}",
                    generation_id=active_gen,
                    layer_id=lyr.layer_id,
                    lod_level=target_lod,
                    primitives=batch,
                    is_final_chunk=False,
                    total_points_count=pts_count,
                )
                chunks.append(chunk)

        if chunks:
            chunks[-1].is_final_chunk = True

        return chunks
