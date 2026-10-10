"""The tag contract: ``route-tags/1``.

Tags live in their own record keyed to a route JSON by code and source hash; the parser contract
``route-kit/1`` is untouched. Every tag carries its evidence (parser units, the rule or model that
produced it, the lookup tables it read) and a review state. Booleans are tri-state: ``unknown``
is never ``False``.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA = "route-tags/1"

Scope = Literal["通用", "出境", "国内", "邮轮"]
Market = Literal["出境", "国内", "unknown"]
Origin = Literal["rule", "llm", "aux"]
Review = Literal["auto_accepted", "needs_review", "confirmed", "corrected"]


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Evidence(_M):
    cite: list[int] = Field(default_factory=list)  # parser evidence unit ids
    quote: str = ""  # verbatim span inside a cited unit (LLM tags)
    rule: str = ""  # "family.key@main-v1" or "aux-<id>@v2"
    lookups: list[str] = Field(default_factory=list)  # "holidays@1" ...
    derived_from: list[str] = Field(default_factory=list)  # parsed fields the rule consumed


class Tag(_M):
    key: str
    value: Any = "unknown"
    scope: Scope = "通用"
    origin: Origin = "rule"
    evidence: Evidence = Field(default_factory=Evidence)
    review: Review = "auto_accepted"
    cardinality: Literal["single", "multi"] = "single"
    note: str = ""  # a short reason shown in review (why unknown, what to check)


class DepartureTags(_M):
    date: date
    source: Literal["explicit", "sailing", "agreed"] = "explicit"
    tags: list[Tag] = Field(default_factory=list)


class Proposal(_M):
    kind: Literal["vocab", "alias"]
    term: str
    definition: str = ""
    dimension: str = ""
    scope: Scope = "通用"
    suggested_canonical: str = ""
    alias_kind: str = ""
    evidence: Evidence = Field(default_factory=Evidence)
    frequency: int = 1


class TaggedWith(_M):
    main_rules: str = ""
    aux_rules: str = ""
    vocab: str = ""
    aliases: str = ""
    lookups: str = ""
    prompt: str = ""
    model: str = ""
    parser_schema: str = ""
    parser: str = ""


class RouteTags(_M):
    schema_: Literal["route-tags/1"] = Field(default=SCHEMA, alias="schema")
    code: str = ""
    sha256: str = ""
    listed_name: str = ""
    market: Market = "unknown"
    product_type: str = "unknown"
    route: list[Tag] = Field(default_factory=list)
    departures: list[DepartureTags] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)  # main vs auxiliary, main wins
    mismatches: list[dict] = Field(default_factory=list)  # derived vs listing product_type
    shadow: list[dict] = Field(default_factory=list)  # shadow-rule outcomes, never live
    issues: list[dict] = Field(default_factory=list)  # tag-level problems for review
    stale: bool = False
    stale_reasons: list[str] = Field(default_factory=list)
    tagged_with: TaggedWith = Field(default_factory=TaggedWith)
    tagged_at: str = ""

    model_config = ConfigDict(extra="ignore", populate_by_name=True, serialize_by_alias=True)

    def get(self, key: str) -> Tag | None:
        return next((t for t in self.route if t.key == key), None)

    def value(self, key: str, default: Any = "unknown") -> Any:
        tag = self.get(key)
        return tag.value if tag else default


class Correction(_M):
    """One human action on a tag, appended to ``corrections.jsonl``."""

    code: str
    sha256: str = ""
    table: Literal["route", "departure"] = "route"
    departure: date | None = None
    key: str
    old_value: Any = None
    new_value: Any = None
    action: Literal["confirm", "correct", "fix_upstream"] = "correct"
    reason: Literal[
        "rule_wrong", "llm_wrong", "parser_wrong", "source_ambiguous", "vocab_missing", "alias_missing", ""
    ] = ""
    parser_field: str = ""  # for fix_upstream: the parsed field at fault
    reviewer: str = ""
    tagged_with: TaggedWith = Field(default_factory=TaggedWith)
    at: str = ""
