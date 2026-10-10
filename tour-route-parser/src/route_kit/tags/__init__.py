"""Tagging stage: structured labels computed from a parsed route, reviewed before use."""

from .engine import mark_stale, tag_route
from .library import Library
from .models import SCHEMA, Correction, RouteTags

__all__ = ["SCHEMA", "Correction", "Library", "RouteTags", "mark_stale", "tag_route"]
