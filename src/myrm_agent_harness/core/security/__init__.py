"""Core security — foundational security primitives used across all layers.

This module provides security types, detection, guards, and policy
enforcement used by both ``agent/`` and ``toolkits/``. It has zero
dependency on ``agent/`` internals, enabling ``toolkits/`` to import
security capabilities without coupling to the agent framework.
"""
