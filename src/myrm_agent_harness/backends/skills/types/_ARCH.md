# backends/skills/types/

## Overview
Skill system data types domain: structured frontmatter contracts, lifecycle enums, runtime instances, metadata, dependency declarations, security scan results, usage statistics, and visibility filters.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Aggregate facade re-exporting all public skill types | ✅ |
| types_contract.py | Core | SkillContract* structured frontmatter contract types (judgments, traps, verifications) | ✅ |
| types_enums.py | Core | SkillTrust, SkillLifecycleStatus, SkillPermission enums | ✅ |
| types_instance.py | Core | SkillInstanceConfig, SkillStateProtocol, SkillInstance implementations | ✅ |
| types_metadata.py | Core | SkillMetadata runtime representation | ✅ |
| types_requires.py | Core | SkillRequires and MCPSkillData dependency types | ✅ |
| types_security.py | Core | SecurityFindingDetail and SecurityScanSummary security audit models | ✅ |
| types_usage.py | Core | SkillUsageStats and SkillUsageRecord usage telemetry models | ✅ |
| types_visibility.py | Core | skill_visible_for_tools tool-conditional visibility filter | ✅ |
| types_coercion.py | Core | Safe list coercion helper for type deserialization | ✅ |

## Module Dependencies

- `pydantic`
- `typing`
