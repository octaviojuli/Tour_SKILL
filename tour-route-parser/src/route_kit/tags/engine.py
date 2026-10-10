"""Tag one parsed route: market and scope, rule families, departures, LLM dimensions,
promoted and auxiliary rules, versions and staleness.

    tags = tag_route(content, listing, library, model=None)

``listing`` is the manifest entry (code, name, days, optional product_type). ``model`` is the
parser's ``Model``; without one the LLM dimensions are skipped and reported.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from ..extract import PARSER
from ..llm import Model
from ..models import SCHEMA as PARSER_SCHEMA
from ..models import RouteContent
from . import dates, dual, llm_tags, rules
from .library import Library
from .models import DepartureTags, Evidence, RouteTags, Tag, TaggedWith


def tag_route(
    content: RouteContent, listing: dict, lib: Library, model: Model | None = None
) -> RouteTags:
    ctx = rules.Ctx(content=content, listing=listing or {}, lib=lib)
    destinations = rules.resolve_destinations(ctx)
    ctx.market = rules.resolve_market(ctx, destinations)
    ctx.scopes = {"通用"} | ({ctx.market} if ctx.market != "unknown" else set())
    rules.product_type(ctx)
    if ctx.product_type == "邮轮":
        ctx.scopes.add("邮轮")
    reference = _reference_date(content)
    departures = dates.parse(content.departure_dates_text, reference)

    rules.skeleton(ctx, destinations)
    rules.meals(ctx)
    rules.stay(ctx)
    rules.transport(ctx)
    rules.sights(ctx)
    rules.shows(ctx)
    rules.shopping(ctx)
    rules.service(ctx, destinations)
    rules.price(ctx)
    if ctx.product_type == "邮轮":
        rules.cruise(ctx, destinations, departures)
    rules.local(ctx, departures)

    tags = RouteTags(
        code=listing.get("code") or content.code,
        sha256=content.source.sha256,
        listed_name=listing.get("name") or content.listed_name,
        market=ctx.market,
        product_type=ctx.product_type,
    )
    tags.departures = _departures(ctx, departures, content)
    _departure_summary(ctx, departures)

    if model is not None:
        llm_tags.llm_tags(ctx, model)
    else:
        ctx.issues.append({"code": "LLM_TAGS_SKIPPED", "path": "llm", "detail": "no model configured"})

    tags.route = ctx.tags
    tags.proposals = ctx.proposals
    tags.issues = ctx.issues
    _apply_promoted(tags, lib)
    dual.apply_aux(tags, lib)
    tags.tagged_with = TaggedWith(
        **lib.versions(),
        prompt=llm_tags.PROMPT_VERSION,
        model=model.name if model is not None else "",
        parser_schema=PARSER_SCHEMA,
        parser=content.source.parser or PARSER,
    )
    tags.tagged_at = datetime.now(UTC).isoformat(timespec="seconds")
    return tags


def _reference_date(content: RouteContent) -> date:
    if content.applicability.start:
        return content.applicability.start
    try:
        return datetime.fromisoformat(content.source.extracted_at).date()
    except ValueError:
        return datetime.now(UTC).date()


def _departures(ctx: rules.Ctx, parsed: dates.Departures, content: RouteContent) -> list[DepartureTags]:
    source = "sailing" if ctx.product_type == "邮轮" else "agreed" if ctx.product_type == "定制游" else "explicit"
    return [
        DepartureTags(date=d, source=source, tags=rules.departure_tags(ctx, d)) for d in parsed.dates
    ]


def _departure_summary(ctx: rules.Ctx, parsed: dates.Departures) -> None:
    c = ctx.content
    ctx.tag("departure_frequency", parsed.frequency, rule="time.frequency", cite=c.departure_dates_cite,
            derived=["departure_dates_text"])
    window = parsed.range
    if not window and c.applicability.start and c.applicability.end:
        window = (c.applicability.start, c.applicability.end)
    if parsed.dates:
        holidays = []
        for dep_date in parsed.dates:
            for t in rules.departure_tags(ctx, dep_date):
                if t.key == "holiday":
                    holidays.extend(x for x in t.value if x not in holidays)
        ctx.tag("holidays_covered", holidays, rule="time.holidays_covered", cardinality="multi",
                cite=c.departure_dates_cite, derived=["departure_dates"],
                lookups=[f"lookups@{ctx.lib.lookups.version}"])
    elif window:
        names = rules.can_depart_in(ctx, window)
        ctx.tag("can_depart_in", names, rule="time.can_depart_in", cardinality="multi",
                cite=c.departure_dates_cite or c.applicability.cite,
                derived=["applicability", "departure_dates_text"],
                lookups=[f"lookups@{ctx.lib.lookups.version}"],
                note=f"仅有日期区间 {window[0]}–{window[1]}，弱标签，检索时排序靠后")
    else:
        ctx.tag("can_depart_in", "unknown", rule="time.can_depart_in", note="原文没有出发日期")


def _apply_promoted(tags: RouteTags, lib: Library) -> None:
    """Promoted rules are main rules in declarative form: they fill unknowns and never conflict."""
    for rule in lib.rules.promoted_rules:
        rule_id = f"promoted-{rule.get('id')}@main-{lib.rules.main_version}"
        for dep, key, value in dual._outcomes(rule, tags):
            holder = dep.tags if dep is not None else tags.route
            existing = next((t for t in holder if t.key == key), None)
            if existing is None:
                holder.append(Tag(key=key, value=value, origin="rule", evidence=Evidence(rule=rule_id)))
            elif existing.cardinality == "multi" and isinstance(existing.value, list):
                if value not in existing.value:
                    existing.value = [*existing.value, value]
                    existing.note = (existing.note + "; " if existing.note else "") + f"{rule_id} 追加"
            elif existing.value in ("unknown", None):
                existing.value = value
                existing.evidence.rule = rule_id


def stale_reasons(tags: RouteTags, lib: Library, model_name: str = "") -> list[str]:
    """Which producers changed since this route was tagged."""
    now = lib.versions()
    reasons = []
    for key, version in now.items():
        if getattr(tags.tagged_with, key) != version:
            reasons.append(f"{key}: {getattr(tags.tagged_with, key)} -> {version}")
    if tags.tagged_with.prompt != llm_tags.PROMPT_VERSION:
        reasons.append(f"prompt: {tags.tagged_with.prompt} -> {llm_tags.PROMPT_VERSION}")
    if model_name and tags.tagged_with.model and tags.tagged_with.model != model_name:
        reasons.append(f"model: {tags.tagged_with.model} -> {model_name}")
    return reasons


def mark_stale(tags: RouteTags, lib: Library, model_name: str = "") -> RouteTags:
    tags.stale_reasons = stale_reasons(tags, lib, model_name)
    tags.stale = bool(tags.stale_reasons)
    return tags
