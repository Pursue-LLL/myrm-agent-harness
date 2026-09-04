# diagnostics/

Doctor concurrent diagnostics and compliance self-audit engine.

| File | Role |
| --- | --- |
| `__init__.py` | Package entrypoint |
| `doctor.py` | Global Doctor — async-parallel environment checks & secrets hygiene |
| `doctor_cli.py` | CLI formatter for doctor reports (grouped by environment/system/security/llm/browser) |
| `compliance.py` | Capability eviction compliance self-audit |
