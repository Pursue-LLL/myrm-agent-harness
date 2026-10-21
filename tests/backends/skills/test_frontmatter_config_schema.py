"""Tests for config_schema parsing in SKILL.md frontmatter."""

import pytest

from myrm_agent_harness.backends.skills._utils import (
    SkillMetadataError,
    parse_skill_frontmatter,
)


def test_config_schema_parsed() -> None:
    content = """---
description: A configurable skill
config-schema:
  type: object
  properties:
    api_key:
      type: string
      format: password
    timeout:
      type: integer
      default: 30
      minimum: 1
      maximum: 300
  required:
    - api_key
---
Body."""
    fm = parse_skill_frontmatter(content, "config-test")
    assert fm.config_schema is not None
    assert fm.config_schema["type"] == "object"
    props = fm.config_schema["properties"]
    assert isinstance(props, dict)
    assert "api_key" in props
    assert "timeout" in props


def test_config_schema_snake_case_alias() -> None:
    content = """---
description: A skill with config_schema (snake_case)
config_schema:
  type: object
  properties:
    name:
      type: string
---
Body."""
    fm = parse_skill_frontmatter(content, "snake-test")
    assert fm.config_schema is not None
    assert fm.config_schema["type"] == "object"


def test_config_schema_absent() -> None:
    content = """---
description: A skill without config schema
---
Body."""
    fm = parse_skill_frontmatter(content, "no-schema")
    assert fm.config_schema is None


def test_config_schema_non_dict_ignored() -> None:
    content = """---
description: Config schema is not a dict
config-schema: just-a-string
---
Body."""
    fm = parse_skill_frontmatter(content, "bad-schema")
    assert fm.config_schema is None


def test_no_frontmatter() -> None:
    with pytest.raises(SkillMetadataError, match="No YAML frontmatter found"):
        parse_skill_frontmatter("No frontmatter here", "test")


def test_invalid_yaml() -> None:
    content = """---
description: [invalid yaml
---
Body."""
    with pytest.raises(SkillMetadataError, match="Invalid YAML syntax"):
        parse_skill_frontmatter(content, "test")


def test_non_dict_frontmatter() -> None:
    content = """---
- list item
---
Body."""
    with pytest.raises(SkillMetadataError, match="must be a YAML object"):
        parse_skill_frontmatter(content, "test")


def test_empty_description() -> None:
    content = """---
description: ""
---
Body."""
    with pytest.raises(SkillMetadataError, match="cannot be empty"):
        parse_skill_frontmatter(content, "test")


def test_long_description_truncated() -> None:
    long_desc = "x" * 2000
    content = f"""---
description: {long_desc}
---
Body."""
    fm = parse_skill_frontmatter(content, "long-desc")
    assert len(fm.description) == 1024


def test_description_angle_brackets_stripped() -> None:
    content = """---
description: A <script>alert('xss')</script> skill
---
Body."""
    fm = parse_skill_frontmatter(content, "xss-test")
    assert "<" not in fm.description
    assert ">" not in fm.description


def test_metadata_and_author() -> None:
    content = """---
description: A skill
author: John Doe
homepage: https://example.com
metadata:
  version: 2.0
---
Body."""
    fm = parse_skill_frontmatter(content, "meta-test")
    assert fm.metadata["author"] == "John Doe"
    assert fm.metadata["homepage"] == "https://example.com"
    assert fm.metadata["version"] == "2.0"


def test_license_and_compatibility() -> None:
    content = """---
description: Licensed skill
license: MIT
compatibility: Python 3.10+
---
Body."""
    fm = parse_skill_frontmatter(content, "license-test")
    assert fm.license == "MIT"
    assert fm.compatibility == "Python 3.10+"


def test_long_compatibility_truncated() -> None:
    long_compat = "y" * 600
    content = f"""---
description: A skill
compatibility: {long_compat}
---
Body."""
    fm = parse_skill_frontmatter(content, "compat-test")
    assert fm.compatibility is not None
    assert len(fm.compatibility) == 500


def test_allowed_domains() -> None:
    content = """---
description: A skill with domains
allowed-domains:
  - api.github.com
  - raw.githubusercontent.com
---
Body."""
    fm = parse_skill_frontmatter(content, "domains-test")
    assert fm.allowed_domains == ["api.github.com", "raw.githubusercontent.com"]


def test_unknown_fields_logged(caplog: pytest.LogCaptureFixture) -> None:
    content = """---
description: Skill with unknown
my_custom_field: value
---
Body."""
    with caplog.at_level("WARNING"):
        parse_skill_frontmatter(content, "unknown-test")
    assert "unknown frontmatter fields" in caplog.text
