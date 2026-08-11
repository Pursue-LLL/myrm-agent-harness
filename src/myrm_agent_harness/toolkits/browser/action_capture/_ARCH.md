# browser/action_capture/

## Overview

Agent-agnostic browser DOM action recorder — captures click/dblclick/fill/select/check/uncheck/press/hover/navigate into structured `ActionStep` sequences for the server Browser Skill Recording Wizard. Text input is recorded session-based (final value emitted once on commit), avoiding fragmented type steps. Supports IME composition protection (fill fragments and candidate-selection presses suppressed), empty-value pruning, keyboard-activation click dedup (Enter submit target resolved from the enclosing form so the synthetic submit click is folded), autocomplete/search-chrome folding, shadow-DOM event targets, SPA navigation capture (history pushState/replaceState/hash), hover steps emitted right before the click they enable (10s window, per-element dedup, aria-haspopup/cursor:pointer gating), press steps carrying keyboard modifiers (Ctrl+Enter), and navigation folding (redirect collapse + action-triggered merge).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public exports: engine, types, serializer | ✅ |
| capture_engine.py | Core | Playwright CDP event listener + bridge (loads JS resource; HOVER steps skip screenshot) | ✅ |
| capture_script.js | Resource | Injected capture JS (event listeners + SPA/shadow-DOM/hover/press logic) | ✅ |
| types.py | Config | ActionType, ActionStep (incl. `modifiers`), CaptureSession | ✅ |
| serializer.py | Core | Session/step JSON (incl. `modifiers`) + natural-language export | ✅ |

## Key Dependencies

- `toolkits/browser/` (Patchright Page)
- No imports from `agent/`, `runtime/`, or `backends/`
