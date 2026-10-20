# gui_chunking/

## Overview
GUI task chunking batch pipeline and row-level checkpoint resume suite.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | GUI task chunking batch pipeline and row-level checkpoint resume suite. | — |
| `batch_chunking_pipeline.py` | Core | Chunked batch pipeline coordinator with skip-ahead resilient resumption. | ✅ |
| `chunking_types.py` | Core | Strongly typed data contracts for GUI task chunking pipeline and row-level checkpoints. | ✅ |
| `row_checkpoint_manifest.py` | Core | Row-level progress checkpoint manifest with crash-safe atomic filesystem persistence. | ✅ |
