"""Sub-agent subsystem — lifecycle management and configuration loading.

Configuration Architecture:
- Framework layer: Provides loading mechanism (config_loader.py)
- Business layer: Provides configuration content and policy

Configuration Loading:
- Business layer explicitly provides configuration directory path
- Framework layer loads and validates YAML files
- See business layer's configs/subagents/README.md for format details
"""
