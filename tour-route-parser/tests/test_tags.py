"""Tag stage: fictional ACME routes, no model calls."""

import json
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from route_kit.models import (  # noqa: E402
    Applicability,
    Day,
    Item,
    Meal,
    Meals,
    Node,
    Price,
    Quality,
    RouteContent,
    Source,
    Stay,
    Transport,
    VisaRule,
)
from route_kit.tags import Correction, Library, RouteTags, mark_stale, tag_route  # noqa: E402
from route_kit.tags import dates, dual, llm_tags, review  # noqa: E402
from route_kit.tags.library import DATA  # noqa: E402

LISTING = {"code": "ACME1", "name": "ACME 线路", "days": 2}


def unit(i, text):
    return {"id": i, "text": text, "page": 1, "line": i, "origin": "text"}


def route(**kw) -> RouteContent:
    units = kw.pop("units", [])
    base = dict(
        code="ACME1",
        source=Source(
            file_name="acme.pdf", media="pdf", sha256="s1", parser="route-kit-2",
            extracted_at="2026-09-30T00:00:00+00:00",
        ),
        units=units,
    )
    base.update(kw)
    content = RouteContent(**base)
    if content.days and not content.days_count:
        content.days_count = max(d.day_end or d.day for d in content.days)
    return content


def london(**extra) -> RouteContent:
    units = [
        unit(1, "伦敦深度 成都直飞 纯玩无购物 26人精品小团"),
        unit(2, "出发日期：10月3日、10月10日"),
        unit(3, "第1天 成都 → 伦敦 参考航班 CA123 23:30-05:40"),
        unit(4, "第2天 伦敦 【大英博物馆 含门票】 住宿：伦敦 4星酒店 早餐:含 午餐:团餐 晚餐:自理"),
        unit(5, "费用包含：中文导游服务、旅游意外保险、英国电子签证费"),
        unit(6, "本线路无购物无自费，全程 0 购物"),
        unit(7, "团费：12800元/人"),
    ]
    kw = dict(
        title="伦敦深度", title_cite=[1], depart_city="成都",
        selling_points=[Item(text="成都直飞", cite=[1]), Item(text="26人精品小团", cite=[1])],
        inclusions=[Item(text="中文导游服务", cite=[5]), Item(text="旅游意外保险", cite=[5]), Item(text="英国电子签证费", cite=[5])],
        prices=[Price(category="tour", amount="12800", currency="CNY", basis="每人", text="团费：12800元/人", cite=[7])],
        departure_dates_text="10月3日、10月10日", departure_dates_cite=[2],
        shopping_status="none", shopping_cite=[6], shopping_quote="无购物",
        days=[
            Day(day=1, day_kind="transit", cities=["成都", "伦敦"], countries=["中国", "英国"], units=[3],
                items=[Node(type="transport", name="成都 → 伦敦", cite=[3],
                            transport=Transport(mode="flight", service_no="CA123", times_text="23:30-05:40", reference=True))],
                stay=Stay(kind="flight", cite=[3])),
            Day(day=2, cities=["伦敦"], countries=["英国"], units=[4],
                items=[Node(type="poi", name="大英博物馆", ticket="included", cite=[4])],
                meals=Meals(breakfast=Meal(status="included", cite=[4]), lunch=Meal(status="included", cite=[4]), dinner=Meal(status="self", cite=[4])),
                stay=Stay(kind="hotel", city="伦敦", grade_text="4星", grade_basis="supplier_description", cite=[4])),
        ],
        units=units,
    )
    kw.update(extra)
    return route(**kw)


@pytest.fixture(scope="module")
def lib():
    return Library()


def values(tags: RouteTags) -> dict:
    return {t.key: t.value for t in tags.route}


# ---------------------------------------------------------------- library and aliases


def test_library_versions_change_with_content(tmp_path, lib):
    copy = tmp_path / "aliases.yaml"
    shutil.copy(DATA / "aliases.yaml", copy)
    from route_kit.tags.library import Aliases

    same = Aliases(copy)
    assert same.version == lib.aliases.version
    copy.write_text(copy.read_text() + "\n# touched\n")
    assert Aliases(copy).version != lib.aliases.version


def test_aliases_resolve_variants_and_suffixes(lib):
    a = lib.aliases
    assert a.canonical("魔都", "city") == "上海"
    assert a.canonical("London", "city") == "伦敦"
    assert a.canonical("伦敦市", "city") == "伦敦"
    assert a.canonical("Hong Kong", "country") == "香港"
    assert a.canonical("火星", "city") is None
    assert a.country_of_city("伦敦") == "英国"
    assert a.continent_of("英国") == "欧洲"
    assert a.region_of("台湾") == "港澳台"


# ---------------------------------------------------------------- dates


def test_departure_dates_parse_lists_years_and_patterns():
    ref = date(2026, 9, 30)
    parsed = dates.parse("10月3日、10日、17日", ref)
    assert parsed.dates == [date(2026, 10, 3), date(2026, 10, 10), date(2026, 10, 17)]
    assert parsed.frequency == "fixed"
    assert dates.parse("2027年1月3日", ref).dates == [date(2027, 1, 3)]
    assert dates.parse("1.15、2.20", ref).dates == [date(2027, 1, 15), date(2027, 2, 20)]  # past months roll forward
    weekly = dates.parse("每周三、周六发团", ref)
    assert weekly.frequency == "weekly" and weekly.weekdays == [2, 5]
    assert dates.parse("天天发团", ref).frequency == "daily"
    ranged = dates.parse("11月1日-12月20日", ref)
    assert ranged.range == (date(2026, 11, 1), date(2026, 12, 20)) and ranged.frequency == "range"
    assert dates.parse("", ref).frequency == "unknown"


# ---------------------------------------------------------------- market, scope, destinations


def test_hk_mo_tw_is_outbound_and_mainland_is_domestic(lib):
    hk = route(days=[Day(day=1, cities=["香港"], countries=["香港"], units=[1])], units=[unit(1, "第1天 香港 迪士尼")])
    assert tag_route(hk, LISTING, lib).market == "出境"
    cn = route(days=[Day(day=1, cities=["上海", "杭州"], countries=["中国"], units=[1])], units=[unit(1, "第1天 上海 杭州")])
    tags = tag_route(cn, LISTING, lib)
    assert tags.market == "国内"
    assert tags.get("visa") is None and tags.get("entry_document") is None
    assert tags.get("attraction_5a_count") is not None  # 国内 scope applies
    assert tag_route(hk, LISTING, lib).get("attraction_5a_count") is None  # skipped for 出境


def test_destinations_weight_visit_days_exclude_transit_and_count_nights(lib):
    tags = tag_route(london(), LISTING, lib)
    dest = values(tags)["destinations"]
    assert dest[0] == {"continent": "欧洲", "country": "英国", "city": "伦敦", "visit_days": 1, "nights": 1}
    assert all(r["city"] != "成都" for r in dest)  # transit day never counts as a visit
    assert values(tags)["primary_destination"] == "英国·伦敦"
    assert values(tags)["depart_city"] == "成都"


def test_unknown_city_becomes_an_alias_candidate_not_a_silent_drop(lib):
    content = route(days=[Day(day=1, cities=["ACME港"], countries=["英国"], units=[1])], units=[unit(1, "第1天 ACME港 观光")])
    tags = tag_route(content, LISTING, lib)
    assert [(p.kind, p.term, p.alias_kind) for p in tags.proposals] == [("alias", "ACME港", "city")]
    assert values(tags)["destinations"][0]["city"] == "ACME港"


# ---------------------------------------------------------------- product type


def test_product_type_is_structural_first(lib):
    cruise = route(days=[Day(day=1, day_kind="at_sea", units=[1], stay=Stay(kind="ship", names=["ACME 梦想号"], cite=[1]))],
                   units=[unit(1, "第1天 海上巡游 住宿：ACME 梦想号")])
    tags = tag_route(cruise, {**LISTING, "product_type": "跟团游"}, lib)
    assert tags.product_type == "邮轮"
    assert tags.get("cruise.sea_days").value == 1 and tags.get("cruise.ship") is not None
    assert any(i["code"] == "PRODUCT_TYPE_MISMATCH" for i in tags.issues)
    one_day = route(days=[Day(day=1, units=[1])], units=[unit(1, "第1天 ACME 古城一日")])
    assert tag_route(one_day, LISTING, lib).product_type == "一日游"
    local = route(days=[Day(day=1, units=[1]), Day(day=2, units=[1])], exclusions=[Item(text="往返大交通机票", cite=[2])],
                  units=[unit(1, "第1天"), unit(2, "费用不含：往返大交通机票")])
    tags = tag_route(local, LISTING, lib)
    assert tags.product_type == "落地散拼" and tags.get("local.duration").value == "多日"
    assert tags.get("direct_flight") is None  # suppressed on 落地散拼
    free_days = [Day(day=n, day_kind="free", units=[1]) for n in range(1, 5)] + [Day(day=5, units=[1])]
    free = route(days=free_days, units=[unit(1, "自由活动")])
    assert tag_route(free, LISTING, lib).product_type == "自由行"  # 4 of 5 days free
    assert tag_route(free, LISTING, lib).get("product_type_basis").value == "structural"
    half = route(days=free_days[:2] + [Day(day=3, units=[1])], units=[unit(1, "自由活动")])
    assert tag_route(half, LISTING, lib).product_type == "半自助"  # 2 of 3


def test_product_type_falls_back_to_listing_then_title(lib):
    empty = route(title="ACME 半自助 5 日", units=[unit(1, "ACME 半自助 5 日")])
    assert tag_route(empty, {**LISTING, "product_type": "私家团"}, lib).product_type == "私家团"
    by_title = tag_route(empty, LISTING, lib)
    assert by_title.product_type == "半自助" and by_title.get("product_type").review == "needs_review"


# ---------------------------------------------------------------- tri-state booleans


def test_pure_play_and_zero_self_paid_need_positive_evidence(lib):
    tags = values(tag_route(london(), LISTING, lib))
    assert tags["pure_play"] is True and tags["zero_self_paid"] is True
    quiet = london(shopping_status="unknown", shopping_cite=[], shopping_quote="")
    assert values(tag_route(quiet, LISTING, lib))["pure_play"] == "unknown"
    shop = london(shopping_status="unknown", shopping_quote="")
    shop.days[1].items.append(Node(type="shopping", name="ACME 皮具中心", cite=[4]))
    shop.days[1].items.append(Node(type="optional", name="ACME 夜游", cite=[4]))
    got = values(tag_route(shop, LISTING, lib))
    assert got["pure_play"] is False and got["shopping_stop_count"] == 1
    assert got["self_paid_count"] == 1 and got["zero_self_paid"] is False
    pending = london()
    pending.quality = Quality(issues=[{"code": "TYPE_CHECK", "path": "D2.items[0]", "detail": "x"}])
    assert values(tag_route(pending, LISTING, lib))["zero_self_paid"] == "unknown"


def test_direct_and_red_eye_flags_and_meal_coverage(lib):
    tags = values(tag_route(london(), LISTING, lib))
    assert tags["direct_flight"] is True and tags["red_eye"] is True
    assert tags["group_meal_ratio"] == "unknown"  # 3 of 6 meals known: below coverage
    day_times = london(selling_points=[Item(text="26人精品小团", cite=[1])])
    day_times.days[0].items[0].transport.times_text = "08:30-12:40"
    got = values(tag_route(day_times, LISTING, lib))
    assert got["direct_flight"] == "unknown" and got["red_eye"] is False
    assert got["small_group"] is True


# ---------------------------------------------------------------- service family


def test_visa_branches_by_destination(lib):
    assert values(tag_route(london(), LISTING, lib))["visa"] == ["电子签"]
    hk = route(
        days=[Day(day=1, cities=["香港"], countries=["香港"], units=[1])],
        traveler_requirements={"visa": VisaRule(type="需持有效港澳通行证及签注", raw="需持有效港澳通行证及签注", cite=[2])},
        units=[unit(1, "第1天 香港"), unit(2, "需持有效港澳通行证及签注")],
    )
    tags = tag_route(hk, LISTING, lib)
    assert tags.get("entry_document").value == ["港澳通行证"]
    assert tags.get("visa") is None  # no foreign destination: no visa dimension
    assert values(tag_route(london(), LISTING, lib))["guide_language"] == "中文"
    assert values(tag_route(london(), LISTING, lib))["insurance_included"] is True


# ---------------------------------------------------------------- time family


def test_departures_get_holiday_season_weekend_and_ranges_only_a_weak_flag(lib):
    tags = tag_route(london(), LISTING, lib)
    assert [d.date for d in tags.departures] == [date(2026, 10, 3), date(2026, 10, 10)]
    first = {t.key: t.value for t in tags.departures[0].tags}
    assert first == {"holiday": ["国庆"], "season": "秋", "weekend_departure": True}
    assert values(tags)["holidays_covered"] == ["国庆"]
    ranged = london(departure_dates_text="", departure_dates_cite=[],
                    applicability=Applicability(start=date(2026, 9, 20), end=date(2026, 10, 5), raw="x", cite=[2]))
    got = tag_route(ranged, LISTING, lib)
    assert got.departures == []
    assert got.get("can_depart_in").value == ["中秋", "国庆"] and "弱标签" in got.get("can_depart_in").note


def test_price_is_stored_raw_never_banded(lib):
    tags = tag_route(london(), LISTING, lib)
    price = tags.get("price_raw")
    assert price.value == [{"amount": "12800", "currency": "CNY", "basis": "每人", "text": "团费：12800元/人"}]
    assert not any("band" in t.key for t in tags.route)


# ---------------------------------------------------------------- LLM verification


def test_llm_words_need_vocabulary_and_a_quote_in_the_cited_unit(lib):
    from route_kit.tags.rules import Ctx

    content = london()
    ctx = Ctx(content=content, listing=LISTING, lib=lib, market="出境", scopes={"通用", "出境"})
    out = llm_tags.TagsOut(
        theme=[
            llm_tags.Pick(word="博物馆", cite=[4], quote="大英博物馆"),
            llm_tags.Pick(word="博物馆", cite=[4], quote="大英博物馆"),  # repeat is kept once
            llm_tags.Pick(word="美食", cite=[4], quote="米其林晚餐"),  # quote not in source
            llm_tags.Pick(word="滑板", cite=[4], quote="大英博物馆"),  # not in vocabulary
            llm_tags.Pick(word="古镇", cite=[4], quote="大英博物馆"),  # 国内-only word on an outbound route
            llm_tags.Pick(word="岸上观光", cite=[4], quote="大英博物馆"),  # 邮轮-only word
        ],
        proposals=[llm_tags.Candidate(term="围炉煮茶", definition="围炉", dimension="theme", cite=[4], quote="大英博物馆")],
    )
    llm_tags.verify(ctx, out, ctx.units, "acme-model")
    theme = next(t for t in ctx.tags if t.key == "theme")
    assert theme.value == ["博物馆"] and theme.review == "needs_review" and theme.origin == "llm"
    codes = sorted(i["code"] for i in ctx.issues)
    assert codes == ["QUOTE_NOT_IN_SOURCE", "WORD_NOT_IN_VOCAB", "WORD_NOT_IN_VOCAB", "WORD_NOT_IN_VOCAB"]
    assert [(p.kind, p.term) for p in ctx.proposals] == [("vocab", "围炉煮茶")]
    assert not any(t.key == "shore_excursion" for t in ctx.tags)  # 邮轮-only dimension: no tag on a bus tour


# ---------------------------------------------------------------- dual-track rules


def aux_lib(tmp_path, rules_yaml: str) -> Library:
    root = tmp_path / "data"
    shutil.copytree(DATA, root)
    (root / "rules" / "aux.yaml").write_text(rules_yaml)
    from route_kit.tags.library import Aliases, Lookups, Rules, Vocabulary

    return Library(
        aliases=Aliases(root / "aliases.yaml"), vocabulary=Vocabulary(root / "vocabulary.yaml"),
        lookups=Lookups(root / "lookups.yaml"),
        rules=Rules(root / "rules" / "main.yaml", root / "rules" / "aux.yaml", root / "rules" / "promoted.yaml"),
    )


AUX = """
version: 2
rules:
  - id: late-guoqing
    auxiliary: true
    status: {status}
    target: {{table: departure, key: holiday, value: 国庆}}
    when:
      - {{feature: departure.month_day, op: between, value: ["10-08", "10-12"]}}
      - {{feature: route.days_count, op: ">=", value: 2}}
  - id: force-pure-play
    auxiliary: true
    status: live
    target: {{table: route, key: pure_play, value: false}}
    when:
      - {{feature: route.market, op: "==", value: 出境}}
  - id: bad-word
    auxiliary: true
    status: live
    target: {{table: route, key: theme, value: 不存在的词}}
    when: []
"""


def test_shadow_rules_record_but_never_write_and_main_wins_conflicts(tmp_path):
    lib = aux_lib(tmp_path, AUX.format(status="shadow"))
    tags = tag_route(london(), LISTING, lib)
    second = {t.key: t.value for t in tags.departures[1].tags}
    assert second["holiday"] == []  # shadow: the live record is untouched
    assert [s["key"] for s in tags.shadow] == ["holiday"] and tags.shadow[0]["date"] == "2026-10-10"
    # main set pure_play=True with a verified quote; the live aux rule says False: main wins, logged
    assert values(tags)["pure_play"] is True
    assert tags.conflicts[0]["key"] == "pure_play" and tags.conflicts[0]["aux_value"] is False
    assert any(i["code"] == "AUX_VALUE_NOT_IN_VOCAB" for i in tags.issues)


def test_live_rules_fill_unknowns_and_append_to_multi_values(tmp_path):
    lib = aux_lib(tmp_path, AUX.format(status="live"))
    tags = tag_route(london(), LISTING, lib)
    second = {t.key: t.value for t in tags.departures[1].tags}
    assert second["holiday"] == ["国庆"]
    holiday = next(t for t in tags.departures[1].tags if t.key == "holiday")
    assert holiday.review == "needs_review" and "aux-late-guoqing" in holiday.note


def test_promote_and_rollback_bump_versions_and_change_tracks(tmp_path):
    lib = aux_lib(tmp_path, AUX.format(status="live"))
    aux_path, promoted_path = lib.rules.aux_path, lib.rules.promoted_path
    before = lib.rules.aux_version
    dual.promote("late-guoqing", aux_path, promoted_path)
    from route_kit.tags.library import Rules

    rules = Rules(lib.rules.main_path, aux_path, promoted_path)
    assert rules.aux_version != before and "+" in rules.main_version
    assert [r["id"] for r in rules.promoted_rules] == ["late-guoqing"]
    assert next(r for r in rules.aux_rules if r["id"] == "late-guoqing")["status"] == "retired"
    lib.rules = rules
    tags = tag_route(london(), LISTING, lib)
    holiday = next(t for t in tags.departures[1].tags if t.key == "holiday")
    assert holiday.value == ["国庆"] and holiday.origin == "rule" and "promoted-late-guoqing" in holiday.note
    with pytest.raises(ValueError):  # a retired (already promoted) rule cannot be promoted again
        dual.promote("late-guoqing", aux_path, promoted_path)
    with pytest.raises(KeyError):
        dual.rollback("no-such-rule", aux_path)
    dual.rollback("force-pure-play", aux_path)
    rules = Rules(lib.rules.main_path, aux_path, promoted_path)
    assert next(r for r in rules.aux_rules if r["id"] == "force-pure-play")["status"] == "retired"


# ---------------------------------------------------------------- stale, corrections, report


def test_stale_when_any_producer_changes(tmp_path, lib):
    tags = tag_route(london(), LISTING, lib)
    assert mark_stale(tags, lib).stale is False
    other = aux_lib(tmp_path, "version: 9\nrules: []\n")
    assert mark_stale(tags, other).stale is True
    assert tags.stale_reasons and tags.stale_reasons[0].startswith("aux_rules")
    tags.tagged_with.model = "old-model"
    assert "model: old-model -> new-model" in mark_stale(tags, lib, "new-model").stale_reasons


def test_corrections_apply_and_feed_the_report(tmp_path, lib):
    path = tmp_path / "corrections.jsonl"
    tags = tag_route(london(), LISTING, lib)
    review.append_correction(path, Correction(code="ACME1", key="hotel_tier", old_value="舒适", new_value="豪华", reason="rule_wrong", reviewer="qa"))
    review.append_correction(path, Correction(code="ACME1", key="guide_language", action="confirm", reviewer="qa"))
    review.append_correction(path, Correction(code="ACME1", key="destinations", action="fix_upstream", reason="parser_wrong", parser_field="days[].cities", reviewer="qa"))
    corrections = review.load_corrections(path)
    assert len(corrections) == 3 and corrections[0].at
    tags = review.apply_corrections(tags, corrections)
    assert tags.get("hotel_tier").value == "豪华" and tags.get("hotel_tier").review == "corrected"
    assert tags.get("guide_language").review == "confirmed"
    assert "上游字段待修" in tags.get("destinations").note
    report = review.batch_report([tags], corrections, lib, gold={})
    assert report["rule_corrections"][0]["rule"].startswith("stay.tier@main-")
    assert report["parser_issues"] == [{"field": "days[].cities", "count": 1}]
    assert report["unknown_share"]["support_24h"] == 1.0
    text = review.render_report(report)
    assert "规则修正统计" in text and "days[].cities" in text


def test_aux_proposals_need_enough_cases_and_a_specific_feature(lib):
    routes = []
    corrections = []
    for i in range(8):
        content = london()
        content.code = f"ACME{i}"
        if i < 6:
            content.days[1].stay.grade_text = "5星"  # the shared feature on corrected routes
        routes.append(tag_route(content, {**LISTING, "code": f"ACME{i}"}, lib))
        if i < 6:
            corrections.append(Correction(code=f"ACME{i}", key="small_group", old_value=True, new_value=False, reason="rule_wrong"))
    proposals = review.propose_aux_rules(routes, corrections, lib)
    assert len(proposals) == 1
    rule = proposals[0]
    assert rule["target"] == {"table": "route", "key": "small_group", "value": False}
    assert rule["when"] == [{"feature": "route.hotel_tier", "op": "==", "value": "豪华"}]
    assert rule["status"] == "shadow" and rule["origin"]["cases"] == 6
    # fewer than min_cases: nothing proposed
    assert review.propose_aux_rules(routes, corrections[:3], lib) == []


def test_shadow_report_compares_with_gold(tmp_path):
    lib = aux_lib(tmp_path, AUX.format(status="shadow"))
    tags = tag_route(london(), LISTING, lib)
    gold = {"ACME1": {"code": "ACME1", "tags": {}, "departures": {"2026-10-10": {"holiday": ["国庆"]}}}}
    report = dual.shadow_report([tags], gold)
    entry = report[next(k for k in report if "late-guoqing" in k)]
    assert entry == {"fired": 1, "compared": 1, "agree": 1, "conflicts_with_main": 0, "agreement": 1.0}


def test_tags_record_round_trips_as_json(lib):
    tags = tag_route(london(), LISTING, lib)
    data = json.loads(tags.model_dump_json(by_alias=True))
    assert data["schema"] == "route-tags/1" and data["tagged_with"]["parser_schema"] == "route-kit/1"
    again = RouteTags.model_validate(data)
    assert again.get("pure_play").evidence.quote == "无购物"


def test_page_embeds_tags_for_the_review_view(lib):
    from route_kit.render import page

    tags = tag_route(london(), LISTING, lib)
    content = json.loads(london().model_dump_json(by_alias=True))
    html = page(content, tags=json.loads(tags.model_dump_json(by_alias=True)))
    assert '"tags"' in html and "renderTags" in html and "</script>" not in html.split("__DATA__")[0][-5:]
    assert "<" not in html.split('id="data">')[1].split("</script>")[0]  # embedded data cannot close the block
    assert "renderTags" in page(content)  # a page without tags still carries the panel code
