# static_index/

## Overview
Centralized static skills index — mirror cache engine plus data models for the prebuilt skill catalog shipped with the product.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public exports for the static skills index engine. | ✅ |
| types.py | Core | Static skills index data models. | ✅ |
| engine.py | Core | `StaticSkillsIndexManager` — centralized static skills index and local mirror cache engine. | ✅ |

## POS
Static index engine with no in-repo runtime consumer. Distinct from `sources/static_index.py`, which is a market HTTP source that reuses the same name.
