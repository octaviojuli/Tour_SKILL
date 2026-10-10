"""One-day sheets with no 第X天 label: the single-day fallback. Fictional ACME samples, no model calls."""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from route_kit.extract import (  # noqa: E402
    DocumentKind,
    LastDayEnd,
    extract,
    file_sha256,
    single_day_fallback,
)
from route_kit.models import DayOut, Meal, Meals, Node, RouteOut, Stay  # noqa: E402
from route_kit.reader import read  # noqa: E402
from route_kit.segment import Layout, Unit, segment  # noqa: E402
from route_kit.tags import Library, tag_route  # noqa: E402

PDF = ROOT / "tests" / "fixtures" / "acme-one-day.pdf"


def layout_of(texts):
    units = [Unit(i, i, t) for i, t in enumerate(texts, start=1)]
    return Layout(units, [], [u.id for u in units], "none", ["NO_DAY_HEADERS"])


def issues():
    return [{"code": "NO_DAY_HEADERS", "path": "days", "detail": ""}]


TIMED = [
    "ACME 古镇一日游",
    "纯玩 0 购物",
    "07:30 酒店接客人",
    "10:00 抵达 ACME 古镇",
    "12:00 中餐",
    "18:30 返回市区",
    "费用包含",
    "景点首道门票",
]


def test_a_timed_programme_without_day_labels_becomes_day_one():
    layout, found = layout_of(TIMED), issues()
    assert single_day_fallback(layout, None, found)
    assert [(b.day, b.day_end, b.header_unit, b.units) for b in layout.days] == [(1, None, 3, [3, 4, 5, 6])]
    assert layout.outside == [1, 2, 7, 8]  # cover before, terms after
    assert layout.method == "single_day"
    assert [i["code"] for i in found] == ["SINGLE_DAY_FALLBACK"]


def test_parts_of_the_day_count_as_time_marks_and_said_one_day_is_enough():
    parts = ["ACME 半日游", "上午 集合", "中午 午餐", "下午 返回", "费用包含"]
    assert single_day_fallback(layout_of(parts), None, issues())
    said = ["ACME 古镇一日游", "游览古镇", "返回市区", "费用包含"]  # no times, but says 一日游
    assert single_day_fallback(layout_of(said), None, issues())
    registered = ["ACME 古镇", "游览古镇", "返回市区", "费用包含"]  # nothing said, listing says 1 day
    assert single_day_fallback(layout_of(registered), 1, issues())


def test_anything_that_reads_longer_than_a_day_is_left_to_the_model_split():
    cases = [
        TIMED[:5] + ["次日 08:00 早餐后返回"] + TIMED[6:],
        ["ACME 二日游"] + TIMED[1:],
        TIMED[:4] + ["D2 古镇深度游"] + TIMED[4:],
        TIMED[:5] + ["晚上 入住 ACME 客栈"] + TIMED[5:],
        TIMED[:5] + ["住宿：ACME 酒店"] + TIMED[5:],
        ["ACME 古镇", "游览古镇", "返回市区", "费用包含"],  # no clock, not said, not registered
    ]
    for texts in cases:
        layout, found = layout_of(texts), issues()
        assert not single_day_fallback(layout, None, found), texts
        assert layout.days == [] and [i["code"] for i in found] == ["NO_DAY_HEADERS"]
    assert not single_day_fallback(layout_of(TIMED), 2, issues())  # registered longer: model decides
    # A one-day sheet whose terms mention 次日 (refunds, notices) is still one day.
    late = TIMED + ["如遇取消，次日退款", "住宿：无"]
    assert single_day_fallback(layout_of(late), None, issues())
    assert single_day_fallback(layout_of(TIMED[:5] + ["住宿：无"] + TIMED[5:]), None, issues())


def test_times_out_of_order_are_not_a_programme():
    shuffled = ["ACME 古镇", "18:30 返回", "07:30 集合", "15:00 游览", "09:00 抵达", "费用包含"]
    assert not single_day_fallback(layout_of(shuffled), None, issues())


def test_a_clock_that_restarts_each_morning_is_several_days_not_one():
    # Day labels drawn as pictures, no 住宿 line: only the clock going back says a new day began.
    days = ["ACME 风光", "08:00 出发", "10:00 游览", "12:00 午餐", "18:30 抵达",
            "08:00 早餐后出发", "11:00 游览", "13:00 午餐", "17:00 返回", "费用包含"]
    assert not single_day_fallback(layout_of(days), None, issues())
    small = ["ACME 古镇", "08:00 集合", "10:00 游览", "09:30 观看表演", "12:00 午餐", "16:00 返回", "费用包含"]
    assert single_day_fallback(layout_of(small), None, issues())  # a half-hour step back is not a new day


class Scripted:
    """Answers each structured call by its schema; never touches the network."""

    name = "scripted"

    def __init__(self):
        self.asked: list[str] = []

    def ask(self, prompt, data, schema, **kwargs):
        self.asked.append(schema.__name__)
        if schema is DocumentKind:
            return DocumentKind(kind="itinerary")
        if schema is LastDayEnd:
            return LastDayEnd(last_unit=data["units"][-1]["id"])
        if schema is RouteOut:
            title = next(u for u in data["units"] if "一日游" in u["text"])
            return RouteOut(title="ACME 古镇土楼经典一日游", title_cite=[title["id"]])
        if schema is DayOut:
            lunch = next(u["id"] for u in data["units"] if u["text"].startswith("12:00"))
            visit = next(u["id"] for u in data["units"] if "和贵楼" in u["text"])
            first = data["units"][0]["id"]
            return DayOut(
                title="厦门 → ACME 古镇 → ACME 土楼群 → 厦门",
                cities=["厦门"],
                day_kind="regular",
                items=[Node(type="poi", name="ACME 和贵楼", visit_mode="inside", cite=[visit])],
                meals=Meals(lunch=Meal(status="included", text="团餐", cite=[lunch])),
                stay=Stay(kind="home", cite=[data["units"][-1]["id"]]),
                title_cite=[first],
            )
        raise AssertionError(f"unexpected call {schema.__name__}")


def test_one_day_pdf_without_headers_parses_to_one_day_with_destinations():
    doc = read(PDF)
    layout = segment(doc)
    assert layout.days == [] and layout.problems == ["NO_DAY_HEADERS"]  # the field-test shape
    model = Scripted()
    meta = {"code": "ACME-ONE", "name": "ACME 古镇土楼一日游", "days": None}
    with ThreadPoolExecutor(max_workers=2) as pool:
        content = extract(doc, layout, model, meta, pool, file_sha256(PDF))
    assert content.days_count == 1 and len(content.days) == 1
    day = content.days[0]
    assert day.day == 1 and day.status == "extracted" and day.day_kind == "regular"
    assert day.cities == ["厦门"] and [n.name for n in day.items] == ["ACME 和贵楼"]
    codes = [i["code"] for i in content.quality.issues]
    assert "SINGLE_DAY_FALLBACK" in codes and "NO_DAY_HEADERS" not in codes
    assert "DayStarts" not in model.asked  # the rule settled it; no model split was asked
    texts = {u["id"]: u["text"] for u in content.units}
    assert not any("费用" in texts[u] for u in day.units)  # terms stay outside day 1
    tags = tag_route(content, meta, Library())
    destinations = tags.get("destinations").value
    assert destinations != "unknown"
    assert destinations[0]["city"] == "厦门" and destinations[0]["country"] == "中国"
    assert tags.value("days_count") == 1 and tags.market == "国内"
    assert tags.product_type == "一日游"


def test_an_ambiguous_file_still_goes_to_the_model_split(tmp_path):
    from route_kit.extract import DayStarts
    from test_route_kit import docx, para

    class Splitter(Scripted):
        def ask(self, prompt, data, schema, **kwargs):
            self.asked.append(schema.__name__)
            if schema is DocumentKind:
                return DocumentKind(kind="itinerary")
            if schema is DayStarts:
                return DayStarts(starts=[])  # the model cannot place the days either
            if schema is RouteOut:
                return RouteOut(title="ACME 古镇")
            raise AssertionError(schema.__name__)

    texts = ["ACME 古镇深度游", "游览古镇老街", "参观 ACME 土楼", "品尝当地小吃", "返回市区", "费用包含", "景点首道门票"]
    path = docx(tmp_path, "".join(para(t) for t in texts))
    doc = read(path)
    layout, model = segment(doc), Splitter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        content = extract(doc, layout, model, {"code": "ACME-AMB", "name": "ACME", "days": None}, pool, "x")
    assert "DayStarts" in model.asked  # no clock, no 一日游, no listing: the model split was asked
    codes = [i["code"] for i in content.quality.issues]
    assert content.days_count == 0 and "SINGLE_DAY_FALLBACK" not in codes and "DAY_SPLIT_REJECTED" in codes
