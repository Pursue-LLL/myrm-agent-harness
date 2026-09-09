# prerequisites/

## Overview
Skill Runtime Prerequisites & System Dependency Check Toolkit. Standardizes the declaration, asynchronous sniffing (`shutil.which` / Python spec), and cross-platform one-click remediation guidance for OS binaries and Python dependencies required by external skills.

## File Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Package | Exports `PrerequisiteProbe`, `SkillPrerequisites`, `PrerequisiteReport`, and remediation helpers |
| `models.py` | Models | Typed contracts: `BinaryDependency`, `PythonDependency`, `SkillPrerequisites`, `DependencyCheckItem`, `PrerequisiteReport`, `DependencyStatus` |
| `remediation.py` | Engine | System detection and one-click package manager installation command generator (macOS brew, Linux apt/pacman/dnf, Windows winget/choco) |
| `remedy.py` | Engine | Package mapping lookup and auto remediation generator |
| `probe.py` | Probe | Lightweight asynchronous host inspector and frontmatter parser |

## Architecture

```
SKILL.md / Market Metadata
       │ (frontmatter parsing)
       ▼
SkillPrerequisites (binaries, python_packages, supported_os)
       │
       ▼
PrerequisiteProbe ───► shutil.which / importlib.util.find_spec
       │
       ├─► DependencyCheckItem (READY / MISSING / VERSION_MISMATCH)
       └─► generate_remediation_command (brew install ... / winget install ...)
       │
       ▼
PrerequisiteReport (is_ready, missing_count, items, summary)
       │
       ▼
Server API / Frontend Badges & One-Click Copy Tool
```
