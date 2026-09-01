"""Pipeline inicial de NLP para Intent-Based Networking."""

from .intent.models import NetworkIntent
from .intent.parser import IntentParser, parse_intent

__all__ = ["IntentParser", "NetworkIntent", "parse_intent"]
