# response_verbosity

Architecture and module inventory for the `response_verbosity` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting response verbosity models, scaler, dehydrator, injector, resolver, and facade suite |
| `dynamic_budget_scaler.py` | Dynamic token budget scaler adapting physical generation limits to verbosity requirements |
| `post_generation_dehydrator.py` | Post-generation text dehydrator extracting concise TL;DR executive digests from verbose output |
| `prompt_discipline_injector.py` | Prompt discipline injector enforcing strict information density and conciseness rules |
| `response_verbosity_suite.py` | Comprehensive facade suite for tri-tier response verbosity and dynamic density tuning |
| `verbosity_preference_resolver.py` | Cascade resolver determining effective response verbosity across multi-tier preferences |
| `verbosity_types.py` | Domain contracts and data models for tri-tier response verbosity and dynamic density tuning |
