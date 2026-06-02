# snapshot/

## Overview
Snapshot module. Provides comprehensive snapshot capabilities, ARIA tree enhancements, and O(1) Self-Healing Locators via spatial BBox metrics.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Snapshot module. Provides comprehensive snapshot capabilities: | ✅ |
| aria_acquisition.py | Core | Layer 1 of the four-layer ARIA snapshot architecture. | ✅ |
| aria_enhancer.py | Core | Layer 3 of the four-layer ARIA snapshot architecture. | ✅ |
| aria_parser.py | Core | Layer 2 of the four-layer ARIA snapshot architecture. | ✅ |
| aria_renderer.py | Core | Layer 4 of the four-layer ARIA snapshot architecture. | ✅ |
| aria_test_utils.py | Test | Testing utilities for parsing rendered ARIA tree strings. | ✅ |
| aria_types.py | Config | Core data types and utility functions for the ARIA Snapshot architecture. | — |
| element_detectors.py | Core | Element detection utilities for snapshot enhancement. | ✅ |
| frame_snapshot.py | Core | Single-frame snapshot manager. Responsibilities: | ✅ |
| observer_manager.py | Core | MutationObserver management for change detection. | ✅ |
| observer_scripts.py | Core | Browser-side JavaScript script constants. Single responsibility: defines DOM mutation | ✅ |
| page_snapshot.py | Core | Multi-frame registry manager. Responsibilities: | ✅ |
| snapshot_types.py | Config | Snapshot data types and enums. | ✅ |
