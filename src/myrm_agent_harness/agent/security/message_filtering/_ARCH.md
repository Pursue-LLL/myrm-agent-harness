# message_filtering/

## Overview
Message filtering framework for AI safety and compliance.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Message filtering framework for AI safety and compliance. | — |
| base.py | Core | Base classes for message filtering framework. | ✅ |
| config_manager.py | Config | ConfigManager for hot-reloading message filter configurations. | ✅ |
| credential_leak_filter.py | Core | Credential leak filter for message security. | ✅ |
| filter_stats.py | Core | Filter performance statistics and monitoring. | ✅ |
| pii_redaction_filter.py | Core | PII redaction filter for message sanitization. | ✅ |
| pipeline.py | Core | Message filter pipeline for composing multiple filters. | ✅ |
| system_role_filter.py | Core | System role message filter for AI safety. | ✅ |
