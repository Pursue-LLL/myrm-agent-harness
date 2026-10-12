# change_guard/

## Overview

ChangeGuard module for review decision lanes and evidence hardening (WS1-WS5). Harness core security module preventing unverified authority changes.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | ChangeGuard module for review decision lanes and evidence hardening (WS1-WS5) — Harness core security module preventing unverified authority changes. | ✅ |
| exceptions_manager.py | Core | File-backed exception management for ChangeGuard — Core exception verification logic enforcing WS4 audit standards. | ✅ |
| guard.py | Core | ChangeGuard engine orchestrating review lanes, authority gates, and evidence hardening — Main engine for WS1-WS5 Agent Authority ChangeGuard. | ✅ |
| lane_evaluator.py | Core | ChangeGuard decision lane evaluator (Lane A vs Lane B) — Evaluator core enforcing review floor and lane separation (WS1, WS2, WS3). | ✅ |
| types.py | Core | Type definitions for ChangeGuard review decision lanes and evidence hardening — Harness core security module implementing deterministic vs review lanes, material-change classification, and hardened evidence bindings. | ✅ |
