# snapshot/

## Overview
Snapshot module. Provides comprehensive snapshot capabilities, ARIA tree enhancements, and O(1) Self-Healing Locators via spatial BBox metrics. The BBox data includes strict `viewport_x`/`viewport_y` offset metrics to ensure precision rendering regardless of page scroll.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Snapshot module. Provides comprehensive snapshot capabilities: | ✅ |
| aria_acquisition.py | Core | Layer 1 of the four-layer ARIA snapshot architecture. | ✅ |
| aria_enhancer.py | Core | Layer 3 of the four-layer ARIA snapshot architecture. Adds ref IDs, semantic positions, scope filtering, nth deduplication, modal blocking layer scoping, and hover surface hints. | ✅ |
| aria_parser.py | Core | Layer 2 of the four-layer ARIA snapshot architecture. | ✅ |
| aria_renderer.py | Core | Layer 4 of the four-layer ARIA snapshot architecture. Formats EnhancedNode tree to YAML or compact text, rendering hover hints and modal blocked statuses. | ✅ |
| aria_test_utils.py | Test | Testing utilities for parsing rendered ARIA tree strings. | ✅ |
| aria_types.py | Config | Core data types and utility functions for the ARIA Snapshot architecture (EnhancedNode with hover_hint and is_blocked). | — |
| element_detectors.py | Core | Element detection utilities for snapshot enhancement (cursor:pointer, bboxes, blocking modal, hover surfaces). | ✅ |
| frame_snapshot.py | Core | Single-frame snapshot manager. Responsibilities: | ✅ |
| observer_manager.py | Core | MutationObserver management for change detection. | ✅ |
| observer_scripts.py | Core | Browser-side JavaScript script constants (DOM mutation, cursor detection, bbox collector, modal blocker, hover surfaces). | ✅ |
| self_healer.py | Core | O(1) spatial BBox self-healing locators with semantic veto when strict locators fail | ✅ |
| page_snapshot.py | Core | Multi-frame registry manager. Responsibilities: | ✅ |
| snapshot_types.py | Config | Snapshot data types and enums. | ✅ |
