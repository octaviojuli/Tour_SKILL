"""Rule families: objective tags computed from parsed fields, never from the model.

Every rule reads ``RouteContent`` fields that the parser already verified against the source,
and writes tags whose evidence names those fields and the units they cite. A fact the
attachment does not state stays ``unknown``; absence never becomes ``False``.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..models import Day, Node, RouteContent
from .dates import Departures
from .library import Library, _norm
from .models import Evidence, Proposal, Tag

HK_MO_TW = {"香港", "澳门", "台湾"}
CRUISE_KINDS = {"at_sea", "port_call", "cruising_no_landing"}
NUM_CN = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}


@dataclass
class Ctx:
    content: RouteContent
    listing: dict
    lib: Library
    market: str = "unknown"
    product_type: str = "unknown"
    scopes: set[str] = field(default_factory=lambda: {"通用"})
    tags: list[Tag] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)

    @property
    def units(self) -> dict[int, str]:
        return {u["id"]: u["text"] for u in self.content.units}

    def rule_id(self, name: str) -> str:
        return f"{name}@main-{self.lib.rules.main_version}"

    def tag(
        self,
        key: str,
        value: Any,
        *,
        rule: str,
        scope: str = "通用",
        cite: list[int] | None = None,
        derived: list[str] | None = None,
        lookups: list[str] | None = None,
        review: str = "auto_accepted",
        cardinality: str = "single",
        note: str = "",
        quote: str = "",
    ) -> Tag | None:
        if scope not in self.scopes:
            return None
        tag = Tag(
            key=key,
            value=value,
            scope=scope,
            origin="rule",
            evidence=Evidence(
                cite=sorted(set(cite or [])),
                quote=quote,
                rule=self.rule_id(rule),
                lookups=lookups or [],
                derived_from=derived or [],
            ),
            review=review,
            cardinality=cardinality,
            note=note,
        )
        self.tags.append(tag)
        return tag

    # ---- text helpers over copied (cited) route-level fields ----
    def cited_items(self) -> list[tuple[str, list[int], str]]:
        """(text, cite, field) for every copied route-level item."""
        c = self.content
        out: list[tuple[str, list[int], str]] = []
        for name in ("inclusions", "exclusions", "cover_facts", "selling_points"):
            for item in getattr(c, name):
                out.append((item.text, item.cite, name))
        for h in c.highlights:
            out.append((h.title + " " + h.text, h.cite, "highlights"))
        for group in c.notices:
            for item in group.items:
                out.append((item.text, item.cite, f"notices.{group.category}"))
        for name in ("single_room", "child", "tips", "cancellation", "deposit"):
            for item in getattr(c.policies, name):
                out.append((item.text, item.cite, f"policies.{name}"))
        if c.title:
            out.append((c.title, c.title_cite, "title"))
        return out

    def find(self, pattern: str, fields: tuple[str, ...] = ()) -> list[tuple[str, list[int], str]]:
        rx = re.compile(pattern)
        return [
            (text, cite, name)
            for text, cite, name in self.cited_items()
            if (not fields or any(name.startswith(f) for f in fields)) and rx.search(text)
        ]

    def propose_alias(self, raw: str, kind: str, cite: list[int]) -> None:
        if not raw or any(p.term == raw and p.alias_kind == kind for p in self.proposals):
            return
        self.proposals.append(
            Proposal(kind="alias", term=raw, alias_kind=kind, evidence=Evidence(cite=cite))
        )


def days_weight(day: Day) -> int:
    return (day.day_end - day.day + 1) if day.day_end and day.day_end >= day.day else 1


def units_mentioning(ctx: Ctx, day: Day, name: str) -> list[int]:
    units = ctx.units
    key = _norm(name)
    return [u for u in day.units if key and key in _norm(units.get(u, ""))][:1]


def transport_nodes(content: RouteContent) -> list[tuple[Day, Node]]:
    return [(d, n) for d in content.days for n in d.items if n.type == "transport" and n.transport]


# ---------------------------------------------------------------- market and scope


def resolve_destinations(ctx: Ctx) -> list[dict]:
    """Per-day cities and countries aggregated into {continent, country, city, visit_days, nights}."""
    lib = ctx.lib.aliases
    visit: dict[tuple[str, str], int] = defaultdict(int)
    nights: dict[tuple[str, str], int] = defaultdict(int)
    cites: dict[tuple[str, str], list[int]] = defaultdict(list)
    for day in ctx.content.days:
        weight = days_weight(day)
        countries = []
        for raw in day.countries:
            canonical = lib.canonical(raw, "country")
            if canonical is None:
                ctx.propose_alias(raw, "country", units_mentioning(ctx, day, raw))
                canonical = raw
            countries.append(canonical)
        cities = []
        for raw in day.cities:
            canonical = lib.canonical(raw, "city")
            if canonical is None:
                ctx.propose_alias(raw, "city", units_mentioning(ctx, day, raw))
                canonical = raw
            country = lib.country_of_city(canonical) or (countries[0] if len(countries) == 1 else "")
            cities.append((country, canonical, raw))
        if day.day_kind != "transit":
            for country, city, raw in cities:
                visit[(country, city)] += weight
                cites[(country, city)].extend(units_mentioning(ctx, day, raw))
            if not cities:
                for country in countries:
                    visit[(country, "")] += weight
        stay_city = day.stay.city
        if day.stay.kind == "hotel" and stay_city:
            canonical = lib.canonical(stay_city, "city") or stay_city
            country = lib.country_of_city(canonical) or (countries[0] if len(countries) == 1 else "")
            nights[(country, canonical)] += weight
            cites[(country, canonical)].extend(day.stay.cite[:1])
    keys = set(visit) | set(nights)
    rows = []
    for country, city in keys:
        rows.append(
            {
                "continent": lib.continent_of(country),
                "country": country,
                "city": city,
                "visit_days": visit.get((country, city), 0),
                "nights": nights.get((country, city), 0),
                "cite": sorted(set(cites.get((country, city), []))),
            }
        )
    rows.sort(key=lambda r: (-r["visit_days"], -r["nights"], r["country"], r["city"]))
    return rows


def resolve_market(ctx: Ctx, destinations: list[dict]) -> str:
    lib = ctx.lib.aliases
    countries = {r["country"] for r in destinations if r["country"]}
    for raw in ctx.content.countries:
        canonical = lib.canonical(raw, "country")
        if canonical:
            countries.add(canonical)
    if not countries:
        return "unknown"
    outbound = ctx.lib.rules.get("market", "hk_mo_tw_is_outbound", default=True)
    foreign = {c for c in countries if c != "中国" and not (c in HK_MO_TW and not outbound)}
    return "出境" if foreign else "国内"


# ---------------------------------------------------------------- family 1: skeleton


def skeleton(ctx: Ctx, destinations: list[dict]) -> None:
    c = ctx.content
    ctx.tag("days_count", c.days_count, rule="skeleton.days_count", derived=["days_count"])
    if destinations:
        ctx.tag(
            "destinations",
            [{k: v for k, v in r.items() if k != "cite"} for r in destinations],
            rule="skeleton.destinations",
            cite=[u for r in destinations for u in r["cite"]],
            derived=["days[].cities", "days[].countries", "days[].stay.city", "days[].day_kind"],
            lookups=[f"aliases@{ctx.lib.aliases.version}"],
            cardinality="multi",
        )
        countries = []
        for r in destinations:
            if r["country"] and r["country"] not in countries:
                countries.append(r["country"])
        ctx.tag("countries", countries, rule="skeleton.countries", cardinality="multi",
                derived=["days[].countries"], lookups=[f"aliases@{ctx.lib.aliases.version}"])
        continents = sorted({r["continent"] for r in destinations if r["continent"]})
        if continents:
            ctx.tag("continents", continents, rule="skeleton.continents", cardinality="multi",
                    lookups=[f"aliases@{ctx.lib.aliases.version}"])
        top = destinations[0]
        label = "·".join(x for x in (top["country"], top["city"]) if x)
        if label:
            ctx.tag("primary_destination", label, rule="skeleton.primary_destination",
                    cite=top["cite"], note=f"visit_days={top['visit_days']}")
    else:
        ctx.tag("destinations", "unknown", rule="skeleton.destinations", note="逐日行程没有可验证的城市或国家")
    depart = ctx.lib.aliases.canonical(c.depart_city, "city") or c.depart_city or "unknown"
    ctx.tag("depart_city", depart, rule="skeleton.depart_city", derived=["depart_city"],
            cite=c.meeting.cite)
    legs = transport_nodes(c)
    modes = Counter(n.transport.mode for _, n in legs if n.transport.mode != "unknown")
    if any(d.day_kind in CRUISE_KINDS for d in c.days):
        main = "cruise"
    elif modes:
        main = modes.most_common(1)[0][0]
    else:
        main = "unknown"
    ctx.tag("main_transport", main, rule="skeleton.main_transport",
            cite=[u for _, n in legs for u in n.cite], derived=["days[].items[type=transport]", "days[].day_kind"])
    flights = [(d, n) for d, n in legs if n.transport.mode == "flight"]
    if ctx.product_type != "落地散拼":
        direct_hits = ctx.find(r"直飞")
        units = ctx.units
        flight_direct = [n for _, n in flights if "直飞" in "".join(units.get(u, "") for u in n.cite)]
        if direct_hits or flight_direct:
            ctx.tag("direct_flight", True, rule="skeleton.direct_flight",
                    cite=[u for _, cite, _ in direct_hits for u in cite] + [u for n in flight_direct for u in n.cite],
                    quote="直飞")
        else:
            ctx.tag("direct_flight", "unknown", rule="skeleton.direct_flight",
                    note="原文没有写明直飞；不从缺省推断为中转")
    red_eye(ctx, flights)


TIME = re.compile(r"(\d{1,2})[:：](\d{2})")


def red_eye(ctx: Ctx, flights: list[tuple[Day, Node]]) -> None:
    rules = ctx.lib.rules
    start = rules.get("red_eye", "start", default="23:00")
    end = rules.get("red_eye", "end", default="06:00")
    s_h, s_m = (int(x) for x in start.split(":"))
    e_h, e_m = (int(x) for x in end.split(":"))

    def is_red(h: int, m: int) -> bool:
        t = h * 60 + m
        return t >= s_h * 60 + s_m or t < e_h * 60 + e_m

    found: list[int] = []
    seen_times = False
    reference = False
    for _, n in flights:
        t = n.transport
        times = [t.departure_local_time, t.arrival_local_time, t.times_text]
        for text in times:
            for h, m in TIME.findall(text or ""):
                seen_times = True
                if 0 <= int(h) < 24 and is_red(int(h), int(m)):
                    found.extend(n.cite)
                    reference = reference or t.reference
    if found:
        ctx.tag("red_eye", True, rule="skeleton.red_eye", cite=found,
                derived=["days[].items[type=transport].transport"],
                note="参考航班，以实际为准" if reference else "")
    elif seen_times:
        ctx.tag("red_eye", False, rule="skeleton.red_eye", derived=["days[].items[type=transport].transport"])
    else:
        ctx.tag("red_eye", "unknown", rule="skeleton.red_eye", note="原文没有写航班时间")


# ---------------------------------------------------------------- family 2: time (per departure)


def _in_window(d: date, start: str, end: str) -> bool:
    """Month-day window, allowed to wrap the year end."""
    md = d.strftime("%m-%d")
    return start <= md <= end if start <= end else md >= start or md <= end


def departure_tags(ctx: Ctx, when: date) -> list[Tag]:
    lk = ctx.lib.lookups
    lookups = [f"lookups@{lk.version}"]
    tags: list[Tag] = []
    holidays: list[str] = []
    for name, window in (lk.holidays.get("fixed") or {}).items():
        if _in_window(when, window["start"], window["end"]):
            holidays.append(name)
    for name, window in ((lk.holidays.get("dated") or {}).get(when.year) or {}).items():
        if date.fromisoformat(window["start"]) <= when <= date.fromisoformat(window["end"]):
            holidays.append(name)
    year_known = when.year in (lk.holidays.get("dated") or {})
    tags.append(
        Tag(key="holiday", value=holidays, cardinality="multi",
            evidence=Evidence(rule=ctx.rule_id("time.holiday"), lookups=lookups, derived_from=["departure_date"]),
            note="" if year_known else f"{when.year} 年的节假日表未录入，只按固定窗口判断")
    )
    season = next((s for s, months in lk.seasons.items() if when.month in months), "unknown")
    tags.append(Tag(key="season", value=season, evidence=Evidence(rule=ctx.rule_id("time.season"), lookups=lookups)))
    tags.append(Tag(key="weekend_departure", value=when.weekday() >= 4,
                    evidence=Evidence(rule=ctx.rule_id("time.weekend_departure"), derived_from=["departure_date"])))
    return tags


def can_depart_in(ctx: Ctx, window: tuple[date, date]) -> list[str]:
    start, end = window
    names: list[str] = []
    d = start
    while d <= end and (d - start).days <= 400:
        for tag in departure_tags(ctx, d):
            if tag.key == "holiday":
                for name in tag.value:
                    if name not in names:
                        names.append(name)
        d = date.fromordinal(d.toordinal() + 1)
    return names


# ---------------------------------------------------------------- family 3: product type


PRIVATE = r"独立成团|一单一团|私家团|私家定制|私人订制|私人定制|专属用车|独立用车"
CUSTOM = r"定制游|定制团|定制线路|定制行程|量身定制"
LOCAL = r"落地散拼|当地参团|当地散拼|散拼团|落地参团|目的地参团"


def derive_product_type(ctx: Ctx) -> tuple[str, str, list[int], str]:
    """(value, basis, cite, note): basis is structural | listing | title | unknown."""
    c = ctx.content
    rules = ctx.lib.rules
    if any(d.day_kind in CRUISE_KINDS or d.stay.kind == "ship" for d in c.days):
        cite = [u for d in c.days if d.day_kind in CRUISE_KINDS or d.stay.kind == "ship" for u in d.stay.cite[:1]]
        return "邮轮", "structural", cite, "day_kind/stay.kind 表明邮轮"
    if c.days_count == 1 and c.days:
        return "一日游", "structural", [], "只有一天"
    for pattern, value in ((CUSTOM, "定制游"), (PRIVATE, "私家团"), (LOCAL, "落地散拼")):
        hits = ctx.find(pattern)
        if hits:
            return value, "structural", [u for _, cite, _ in hits for u in cite], hits[0][0][:40]
    flights = [n for _, n in transport_nodes(c) if n.transport.mode == "flight"]
    no_big_transport = ctx.find(r"机票|大交通|往返交通", ("exclusions",))
    if not flights and no_big_transport and c.days_count >= 1:
        return "落地散拼", "structural", [u for _, cite, _ in no_big_transport for u in cite], "不含大交通且无航班节点"
    if not c.days:
        return "unknown", "unknown", [], "没有逐日行程"
    free_days = sum(days_weight(d) for d in c.days if d.day_kind == "free")
    total = sum(days_weight(d) for d in c.days)
    free_ratio = free_days / total if total else 0.0
    guide_in = ctx.find(r"导游|领队|司导|司兼导", ("inclusions",))
    guide_out = ctx.find(r"(?:不含|无)(?:导游|领队)|导游.{0,4}自理", ("exclusions", "inclusions", "notices"))
    ziyou = rules.get("product_type", "自由行_min_free_ratio", default=0.8)
    banzizhu = rules.get("product_type", "半自助_min_free_ratio", default=0.3)
    if free_ratio >= ziyou or (guide_out and not guide_in and free_ratio >= 0.5):
        return "自由行", "structural", [u for _, cite, _ in guide_out for u in cite], f"自由活动占比 {free_ratio:.2f}"
    if free_ratio >= banzizhu:
        return "半自助", "structural", [u for _, cite, _ in guide_in for u in cite], f"自由活动占比 {free_ratio:.2f}"
    if guide_in or any(d.items for d in c.days):
        return "跟团游", "structural", [u for _, cite, _ in guide_in for u in cite], f"自由活动占比 {free_ratio:.2f}"
    return "unknown", "unknown", [], "结构无法判断"


TITLE_TYPES = (
    (r"自由行", "自由行"), (r"半自助|半自由", "半自助"), (r"跟团|纯玩团|品质团", "跟团游"),
    (r"邮轮|游轮", "邮轮"), (r"一日游", "一日游"),
)


def product_type(ctx: Ctx) -> None:
    value, basis, cite, note = derive_product_type(ctx)
    listed = (ctx.listing or {}).get("product_type") or ""
    if basis == "unknown":
        if listed:
            value, basis, note = listed, "listing", "结构无法判断，采用登记的产品类型"
        else:
            title = ctx.content.title or ctx.content.listed_name
            for pattern, kind in TITLE_TYPES:
                if re.search(pattern, title):
                    value, basis, note = kind, "title", "结构和登记都无法判断，按标题"
                    break
    if listed and basis == "structural" and listed != value:
        ctx.issues.append({"code": "PRODUCT_TYPE_MISMATCH", "path": "product_type",
                           "detail": f"结构判断 {value}，登记 {listed}"})
    ctx.product_type = value
    ctx.tag("product_type", value, rule="product_type", cite=cite, derived=["days[].day_kind", "inclusions", "exclusions"],
            review="needs_review" if basis != "structural" or listed and listed != value else "auto_accepted",
            note=f"{basis}: {note}")
    ctx.tag("product_type_basis", basis, rule="product_type", note=note)


# ---------------------------------------------------------------- family 6: 吃住行游娱购

MEAL_STANDARD = re.compile(r"(\d{2,4})\s*元\s*/\s*人\s*/\s*(?:正)?餐|餐标\s*(\d{2,4})")


def meals(ctx: Ctx) -> None:
    c = ctx.content
    rules = ctx.lib.rules
    hits = ctx.find(MEAL_STANDARD.pattern)
    if hits:
        text, cite, _ = hits[0]
        amount = next(g for g in MEAL_STANDARD.search(text).groups() if g)
        ctx.tag("meal_standard_cny", int(amount), rule="meals.standard", cite=cite, quote=text[:40])
    else:
        ctx.tag("meal_standard_cny", "unknown", rule="meals.standard", note="原文没有写餐标")
    statuses = [getattr(d.meals, m).status for d in c.days for m in ("breakfast", "lunch", "dinner")]
    known = [s for s in statuses if s in ("included", "self")]
    total = len(statuses)
    coverage = len(known) / total if total else 0.0
    min_cov = rules.get("meals", "min_coverage", default=0.6)
    cite = [u for d in c.days for m in ("breakfast", "lunch", "dinner") for u in getattr(d.meals, m).cite]
    if total and coverage >= min_cov:
        included = sum(1 for s in known if s == "included")
        ctx.tag("group_meal_ratio", round(included / len(known), 2), rule="meals.group_ratio", cite=cite,
                derived=["days[].meals"], note=f"meals_known={len(known)}/{total}")
    else:
        ctx.tag("group_meal_ratio", "unknown", rule="meals.group_ratio",
                note=f"餐食状态覆盖率 {coverage:.2f} 低于 {min_cov}")
    breakfasts = [d.meals.breakfast.status for d in c.days]
    b_known = [s for s in breakfasts if s in ("included", "self")]
    if breakfasts and len(b_known) / len(breakfasts) >= min_cov:
        inc = sum(1 for s in b_known if s == "included")
        value = True if inc == len(b_known) else False if inc == 0 else "partial"
        ctx.tag("breakfast_included", value, rule="meals.breakfast", derived=["days[].meals.breakfast"],
                cite=[u for d in c.days for u in d.meals.breakfast.cite], note=f"{inc}/{len(b_known)}")
    else:
        ctx.tag("breakfast_included", "unknown", rule="meals.breakfast", note="早餐状态覆盖率不足")


STARS = re.compile(r"(\d|[一二两三四五六七])\s*[星钻]")


def stay(ctx: Ctx) -> None:
    c = ctx.content
    rules = ctx.lib.rules
    stars: list[int] = []
    cite: list[int] = []
    basis = "unknown"
    homestay = False
    for d in c.days:
        s = d.stay
        if s.kind != "hotel":
            continue
        if re.search(r"民宿|客栈|特色住宿", s.grade_text + " ".join(s.names)):
            homestay = True
            cite.extend(s.cite[:1])
        for m in STARS.finditer(s.grade_text):
            raw = m.group(1)
            stars.append(int(raw) if raw.isdigit() else NUM_CN.get(raw, 0))
            cite.extend(s.cite[:1])
            basis = s.grade_basis if s.grade_basis != "unknown" else "supplier_description"
    tiers = rules.get("hotel_tier", default={}) or {}
    if stars:
        typical = Counter(stars).most_common(1)[0][0]
        tier = "unknown"
        for name, spec in tiers.items():
            lo, hi = spec.get("min_stars", 0), spec.get("max_stars", 99)
            if lo <= typical <= hi:
                tier = name
                break
        if homestay:
            tier = "特色民宿"
        ctx.tag("hotel_tier", tier, rule="stay.tier", cite=cite, derived=["days[].stay.grade_text", "days[].stay.grade_basis"],
                note=f"basis={basis}; stars={typical}")
    elif homestay:
        ctx.tag("hotel_tier", "特色民宿", rule="stay.tier", cite=cite, derived=["days[].stay"])
    else:
        ctx.tag("hotel_tier", "unknown", rule="stay.tier", note="原文没有写酒店星级")


def transport(ctx: Ctx) -> None:
    c = ctx.content
    legs = transport_nodes(c)
    modes = sorted({n.transport.mode for _, n in legs if n.transport.mode not in ("unknown", "flight")})
    ctx.tag("local_vehicle", modes or "unknown", rule="transport.local_vehicle", cardinality="multi",
            cite=[u for _, n in legs for u in n.cite], derived=["days[].items[type=transport]"])
    inc = ctx.find(r"接送机|接机|送机|机场接送|接送服务", ("inclusions",))
    exc = ctx.find(r"接送机|接机|送机|机场接送", ("exclusions",))
    if inc:
        ctx.tag("airport_transfer", True, rule="transport.airport_transfer", cite=[u for _, ci, _ in inc for u in ci])
    elif exc:
        ctx.tag("airport_transfer", False, rule="transport.airport_transfer", cite=[u for _, ci, _ in exc for u in ci])
    else:
        ctx.tag("airport_transfer", "unknown", rule="transport.airport_transfer")


def sights(ctx: Ctx) -> None:
    c = ctx.content
    pois = [n for d in c.days for n in d.items if n.type == "poi"]
    children = [ch for d in c.days for n in d.items if n.type == "group" for ch in n.children]
    photo = [n for d in c.days for n in d.items if n.type == "photo_spot"]
    ctx.tag("attraction_count", len(pois) + len(children), rule="sights.count",
            cite=[u for n in pois + children for u in n.cite][:40], derived=["days[].items[type=poi]", "group.children"])
    ctx.tag("photo_spot_count", len(photo), rule="sights.photo_spots", cite=[u for n in photo for u in n.cite])
    tickets = [n.ticket for n in pois + children]
    known = [t for t in tickets if t in ("included", "excluded", "free_entry")]
    if known:
        paid = sum(1 for t in known if t == "included")
        ctx.tag("ticket_included_ratio", round(paid / len(known), 2), rule="sights.ticket_ratio",
                derived=["days[].items[].ticket"], note=f"known={len(known)}/{len(tickets)}")
    else:
        ctx.tag("ticket_included_ratio", "unknown", rule="sights.ticket_ratio", note="门票状态都未说明")
    if ctx.market == "国内":
        ctx.tag("attraction_5a_count", "unknown", rule="sights.5a", scope="国内",
                note="景区等级库未接入；接入后按 poi 名称匹配")


def shows(ctx: Ctx) -> None:
    acts = [n for d in ctx.content.days for n in d.items if n.type == "activity"]
    showy = [n for n in acts if re.search(r"秀|演出|表演|剧场|歌舞|音乐会", n.name)]
    ctx.tag("show_count", len(showy), rule="entertainment.shows", cite=[u for n in showy for u in n.cite])


def shopping(ctx: Ctx) -> None:
    c = ctx.content
    stops = [n for d in c.days for n in d.items if n.type == "shopping"]
    optional = [n for d in c.days for n in d.items if n.type in ("optional", "package")]
    ctx.tag("shopping_stop_count", len(stops) + len(c.shopping), rule="shopping.stops",
            cite=[u for n in stops for u in n.cite] + [u for s in c.shopping for u in s.cite],
            derived=["days[].items[type=shopping]", "shopping"])
    if c.shopping_status == "none" and c.shopping_quote:
        ctx.tag("pure_play", True, rule="shopping.pure_play", cite=c.shopping_cite, quote=c.shopping_quote,
                derived=["shopping_status", "shopping_quote"])
    elif stops or c.shopping or c.shopping_status == "present":
        ctx.tag("pure_play", False, rule="shopping.pure_play",
                cite=[u for n in stops for u in n.cite] + [u for s in c.shopping for u in s.cite],
                derived=["days[].items[type=shopping]", "shopping"])
    else:
        ctx.tag("pure_play", "unknown", rule="shopping.pure_play", note="原文没有明确承诺无购物，也没有列出购物点")
    count = len(optional) + len(c.optional_items)
    ctx.tag("self_paid_count", count, rule="shopping.self_paid",
            cite=[u for n in optional for u in n.cite] + [u for o in c.optional_items for u in o.cite],
            derived=["days[].items[type=optional|package]", "optional_items"])
    open_checks = [i for i in c.quality.issues if i["code"] in ("TYPE_CHECK", "TYPE_FROM_SECTION", "TYPE_UNSUPPORTED")]
    if count == 0 and not open_checks and c.days:
        ctx.tag("zero_self_paid", True, rule="shopping.zero_self_paid", derived=["self_paid_count", "quality.issues"])
    elif count > 0:
        ctx.tag("zero_self_paid", False, rule="shopping.zero_self_paid", derived=["self_paid_count"])
    else:
        ctx.tag("zero_self_paid", "unknown", rule="shopping.zero_self_paid",
                note=f"{len(open_checks)} 个自费类型问题待核对" if open_checks else "没有逐日行程")


# ---------------------------------------------------------------- family 7: service guarantees


def service(ctx: Ctx, destinations: list[dict]) -> None:
    c = ctx.content
    zh = ctx.find(r"中文(?:导游|领队|司导|司机兼导游|服务|讲解)|华语(?:导游|领队)|中文司兼导")
    bi = ctx.find(r"双语(?:导游|领队|司导)")
    none = ctx.find(r"(?:不含|无|不提供|没有)(?:导游|领队|司导)|无导游|无领队")
    if bi:
        ctx.tag("guide_language", "双语", rule="service.guide_language", cite=[u for _, ci, _ in bi for u in ci], quote=bi[0][0][:30])
    elif zh:
        ctx.tag("guide_language", "中文", rule="service.guide_language", cite=[u for _, ci, _ in zh for u in ci], quote=zh[0][0][:30])
    elif none:
        ctx.tag("guide_language", "无导", rule="service.guide_language", cite=[u for _, ci, _ in none for u in ci], quote=none[0][0][:30])
    else:
        ctx.tag("guide_language", "unknown", rule="service.guide_language", note="原文没有写导游语言")
    ins = c.traveler_requirements.insurance
    if ins.included is not None:
        ctx.tag("insurance_included", ins.included, rule="service.insurance", cite=ins.cite, derived=["traveler_requirements.insurance"])
    else:
        in_inc = ctx.find(r"保险", ("inclusions",))
        in_exc = ctx.find(r"保险", ("exclusions",))
        if in_inc and not in_exc:
            ctx.tag("insurance_included", True, rule="service.insurance", cite=[u for _, ci, _ in in_inc for u in ci])
        elif in_exc and not in_inc:
            ctx.tag("insurance_included", False, rule="service.insurance", cite=[u for _, ci, _ in in_exc for u in ci])
        else:
            ctx.tag("insurance_included", "unknown", rule="service.insurance",
                    note="包含和不含都提到保险，需人工核对" if in_inc and in_exc else "原文没有写保险")
    h24 = ctx.find(r"24\s*小时|24\s*[hH]")
    ctx.tag("support_24h", bool(h24) or "unknown", rule="service.support_24h", cite=[u for _, ci, _ in h24 for u in ci],
            note="" if h24 else "原文没有写 24 小时服务")
    minimum = c.formation.minimum_travelers
    small = ctx.find(r"(\d{1,2})\s*人\s*(?:精品)?(?:小团|小包团|封顶|成团)|(?:精品)?小团", ("selling_points", "highlights", "cover_facts", "title"))
    if minimum is not None:
        ctx.tag("min_travelers", minimum, rule="service.group_size", cite=c.formation.cite, derived=["formation.minimum_travelers"])
    else:
        ctx.tag("min_travelers", "unknown", rule="service.group_size")
    if small:
        text, cite, _ = small[0]
        m = re.search(r"(\d{1,2})\s*人", text)
        ctx.tag("small_group", True, rule="service.small_group", cite=cite, quote=text[:30],
                note=f"max={m.group(1)}" if m else "")
    else:
        ctx.tag("small_group", "unknown", rule="service.small_group")
    private = ctx.find(PRIVATE)
    ctx.tag("private_group", True if private else "unknown", rule="service.private_group",
            cite=[u for _, ci, _ in private for u in ci])
    entry_documents(ctx, destinations)
    if c.meeting.domestic_connection:
        ctx.tag("domestic_connection", True, rule="service.domestic_connection", cite=c.meeting.cite,
                quote=c.meeting.domestic_connection[:40], derived=["meeting.domestic_connection"])
    else:
        ctx.tag("domestic_connection", "unknown", rule="service.domestic_connection")


def entry_documents(ctx: Ctx, destinations: list[dict]) -> None:
    """Foreign destinations carry a visa type; 港澳台 destinations carry an entry document."""
    if ctx.market != "出境":
        return
    lib = ctx.lib.aliases
    countries = {r["country"] for r in destinations if r["country"]}
    foreign = {x for x in countries if x != "中国" and x not in HK_MO_TW}
    hkmt = countries & HK_MO_TW
    visa = ctx.content.traveler_requirements.visa
    texts = [(visa.type, visa.cite)] if visa.type else []
    texts += [(t, ci) for t, ci, _ in ctx.find(r"签证|免签|落地签|电子签|通行证|入台证|签注", ("notices.visa_documents", "inclusions", "exclusions", "selling_points", "cover_facts", "policies"))]
    if foreign:
        found = []
        for text, cite in texts:
            for kind in ("免签", "落地签", "电子签", "贴纸签"):
                if any(a in _norm(text) for a in lib.spellings(kind, "visa_type")):
                    found.append((kind, text, cite))
        if found:
            kinds = []
            for k, _, _ in found:
                if k not in kinds:
                    kinds.append(k)
            ctx.tag("visa", kinds, rule="service.visa", scope="出境", cardinality="multi",
                    cite=[u for _, _, ci in found for u in ci], quote=found[0][1][:40],
                    derived=["traveler_requirements.visa", "notices.visa_documents"],
                    lookups=[f"aliases@{lib.version}"])
        else:
            ctx.tag("visa", "unknown", rule="service.visa", scope="出境", note="原文没有写签证类型")
    if hkmt:
        found = []
        for text, cite in texts:
            for kind in ("港澳通行证", "台湾通行证", "入台证"):
                if any(a in _norm(text) for a in lib.spellings(kind, "entry_document")):
                    found.append((kind, text, cite))
        kinds = []
        for k, _, _ in found:
            if k not in kinds:
                kinds.append(k)
        ctx.tag("entry_document", kinds or "unknown", rule="service.entry_document", scope="出境", cardinality="multi",
                cite=[u for _, _, ci in found for u in ci], derived=["notices.visa_documents"],
                lookups=[f"aliases@{lib.version}"], note="" if kinds else "原文没有写通行证要求")


# ---------------------------------------------------------------- family 8: price (raw only)


def price(ctx: Ctx) -> None:
    rows = [
        {"amount": p.amount, "currency": p.currency, "basis": p.basis, "text": p.text}
        for p in ctx.content.prices
        if p.category == "tour" and p.amount
    ]
    ctx.tag("price_raw", rows or "unknown", rule="price.raw", cardinality="multi",
            cite=[u for p in ctx.content.prices if p.category == "tour" for u in p.cite],
            derived=["prices[category=tour]"], note="同业价，非实时报价；分档在检索时按零售价计算")


# ---------------------------------------------------------------- 邮轮 branch


CABIN = (("内舱", r"内舱|内侧房|内景房"), ("海景", r"海景房|海景舱|外舱"), ("阳台", r"阳台房|阳台舱"), ("套房", r"套房"))


def cruise(ctx: Ctx, destinations: list[dict], departures: Departures) -> None:
    c = ctx.content
    lib = ctx.lib
    ships = [n for d in c.days if d.stay.kind == "ship" for n in d.stay.names]
    ship_cite = [u for d in c.days if d.stay.kind == "ship" for u in d.stay.cite[:1]]
    candidates = ships + [c.title] + [f.text for f in c.cover_facts]
    ship = line = ""
    for raw in candidates:
        canonical = lib.aliases.canonical(raw, "ship")
        if canonical:
            ship = canonical
            line = lib.aliases.place(canonical, "ship").line
            break
    for raw in candidates:
        if line:
            break
        for token in re.split(r"[\s·|丨+]+", raw or ""):
            canonical = lib.aliases.canonical(token, "cruise_line")
            if canonical:
                line = canonical
                break
    if ships and not ship:
        ctx.propose_alias(ships[0], "ship", ship_cite)
    ctx.tag("cruise.ship", ship or "unknown", rule="cruise.ship", scope="邮轮", cite=ship_cite,
            derived=["days[].stay.names"], lookups=[f"aliases@{lib.aliases.version}"])
    ctx.tag("cruise.line", line or "unknown", rule="cruise.line", scope="邮轮", cite=ship_cite + c.title_cite,
            lookups=[f"aliases@{lib.aliases.version}"])
    cabin_text = " ".join([d.stay.room_type for d in c.days] + [p.text for p in c.prices])
    cabins = [name for name, rx in CABIN if re.search(rx, cabin_text)]
    ctx.tag("cruise.cabin_type", cabins or "unknown", rule="cruise.cabin", scope="邮轮", cardinality="multi",
            cite=[u for p in c.prices for u in p.cite] + [u for d in c.days for u in d.stay.cite[:1]],
            derived=["days[].stay.room_type", "prices[].text"])
    countries = {r["country"] for r in destinations if r["country"]}
    regions = [name for name, members in lib.lookups.cruise_regions.items() if countries & set(members)]
    ctx.tag("cruise.region", regions or "unknown", rule="cruise.region", scope="邮轮", cardinality="multi",
            lookups=[f"lookups@{lib.lookups.version}"], derived=["destinations"])
    sea = sum(days_weight(d) for d in c.days if d.day_kind in ("at_sea", "cruising_no_landing"))
    port = sum(days_weight(d) for d in c.days if d.day_kind == "port_call")
    ctx.tag("cruise.sea_days", sea, rule="cruise.days", scope="邮轮", derived=["days[].day_kind"])
    ctx.tag("cruise.port_days", port, rule="cruise.days", scope="邮轮", derived=["days[].day_kind"])
    if sea + port:
        ctx.tag("cruise.port_weight", round(port / (sea + port), 2), rule="cruise.days", scope="邮轮")
    ports = []
    cite = []
    for d in c.days:
        if d.port_call and d.port_call.port:
            canonical = lib.aliases.canonical(d.port_call.port, "city") or d.port_call.port
            ports.append({"day": d.day, "port": canonical, "arrive": d.port_call.arrive_text, "depart": d.port_call.depart_text})
            cite.extend(d.port_call.cite)
    ctx.tag("cruise.ports", ports or "unknown", rule="cruise.ports", scope="邮轮", cardinality="multi", cite=cite,
            derived=["days[].port_call"])


# ---------------------------------------------------------------- 落地散拼 branch


def local(ctx: Ctx, departures: Departures) -> None:
    c = ctx.content
    if ctx.product_type != "落地散拼":
        return
    if c.days_count == 1:
        half = ctx.find(r"半日|半天")
        duration = "半日" if half else "一日"
        cite = [u for _, ci, _ in half for u in ci]
    else:
        duration, cite = "多日", []
    ctx.tag("local.duration", duration, rule="local.duration", cite=cite, derived=["days_count"])
    ctx.tag("local.departure_frequency", departures.frequency, rule="local.frequency",
            cite=c.departure_dates_cite, derived=["departure_dates_text"])
    pickup = ctx.find(r"酒店接送|接送|上门接|酒店接", ("inclusions", "selling_points", "highlights", "notices"))
    if pickup:
        ctx.tag("local.pickup", "酒店接送", rule="local.pickup", cite=[u for _, ci, _ in pickup for u in ci], quote=pickup[0][0][:30])
    elif c.meeting.location:
        ctx.tag("local.pickup", "集合点", rule="local.pickup", cite=c.meeting.cite, quote=c.meeting.location[:30])
    else:
        ctx.tag("local.pickup", "unknown", rule="local.pickup")
