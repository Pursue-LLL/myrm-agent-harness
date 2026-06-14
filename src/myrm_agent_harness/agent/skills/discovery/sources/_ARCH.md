# sources/

## Overview
Skill data sources. Each source implements the `SkillSource` protocol (base.py) and is
registered in `service.py`. Sources are queried in parallel with per-source timeout;
individual failures are logged and silently skipped.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill data sources. | — |
| aliyun.py | Core | Aliyun AgentExplorer 技能搜索源（需 AK/SK，无凭据时静默跳过）。 | ✅ |
| base.py | Core | Provides SkillSource protocol. | ✅ |
| clawhub.py | Core | Provides ClawHubSource. | ✅ |
| github.py | Core | Provides GitHubSkillSource, GitHubRef, parse_github_url. | ✅ |
| lobehub.py | Core | Provides LobeHubSource. | ✅ |
| modelscope.py | Core | ModelScope 魔搭社区技能搜索源（搜索无需认证，80K+ 技能）。 | ✅ |
| prebuilt.py | Core | Prebuilt skill search source. | ✅ |
| skills_sh.py | Core | Provides SkillsShSource. | ✅ |

## Key Dependencies

- `backends`
