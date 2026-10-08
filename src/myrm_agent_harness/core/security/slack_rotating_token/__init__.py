"""Slack Rotating Token Classification and Scope Inspection Suite.

Provides semantic classification for Slack tokens (static vs rotating vs refresh),
Bearer prefix stripping, and OAuth scope extraction.
"""

from .classifier import SlackTokenClassifier
from .scope_inspector import SlackScopeInspector
from .types import (
    SlackScopeInspection,
    SlackTokenCategory,
    SlackTokenClassification,
    SlackTokenType,
)

__all__ = [
    "SlackScopeInspection",
    "SlackTokenCategory",
    "SlackTokenClassification",
    "SlackTokenClassifier",
    "SlackTokenType",
    "SlackScopeInspector",
]
