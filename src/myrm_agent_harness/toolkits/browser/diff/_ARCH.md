# diff/

## Overview
Screenshot diff utilities — unified comparison system.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Screenshot diff utilities — unified comparison system. | — |
| accurate_comparator.py | Core | Pixel-level screenshot comparison module for the browser toolkit. Performs per-pixel | ✅ |
| fast_comparator.py | Core | Fast screenshot comparison tool. Uses dHash (difference hash) algorithm for O(1) visual similarity d | ✅ |
| screenshot_comparator.py | Core | Screenshot comparison manager. Provides a unified interface for fast and accurate comparison, with a | ✅ |
| types.py | Config | Unified type system for screenshot diff. Defines Protocol and dataclass types for type safety. | ✅ |
