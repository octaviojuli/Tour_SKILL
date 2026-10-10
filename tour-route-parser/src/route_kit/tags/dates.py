"""Departure dates from the attachment's own words.

``departure_dates_text`` is copied text ("11月5日、12日、19日", "2026.1.3", "每周三发团",
"天天发团"); this turns it into dates where it names them, and into a frequency where it
names a pattern. A year the text leaves out is taken from the applicability range or the
parse date, moved forward when the date would otherwise lie well in the past.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

FULL = re.compile(r"(20\d{2})\s*[年.\-/]\s*(\d{1,2})\s*[月.\-/]\s*(\d{1,2})\s*日?")
MONTH_DAYS = re.compile(r"(\d{1,2})\s*月\s*((?:\d{1,2}\s*日?\s*[、,，/]?\s*)+)")
NUMERIC = re.compile(r"(?<![\d.])(\d{1,2})\s*[./]\s*(\d{1,2})(?![\d.])")
WEEKDAY = re.compile(r"(?:每?周|星期|礼拜)([一二三四五六日天])")
DAILY = re.compile(r"天天发团|每天发团|每日发团|天天出发|每天出发|天天发")
RANGE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?\s*[-—–~至到]\s*(?:(\d{1,2})\s*月\s*)?(\d{1,2})\s*日?")

WEEKDAY_INDEX = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


@dataclass
class Departures:
    dates: list[date] = field(default_factory=list)
    frequency: str = "unknown"  # daily | weekly | fixed | range | unknown
    weekdays: list[int] = field(default_factory=list)
    range: tuple[date, date] | None = None


def _valid(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _year_for(month: int, day: int, reference: date) -> date | None:
    """The next occurrence of month/day on or after (reference - 60 days)."""
    candidate = _valid(reference.year, month, day)
    if candidate is None:
        return None
    if candidate < reference - timedelta(days=60):
        return _valid(reference.year + 1, month, day)
    return candidate


def parse(text: str, reference: date) -> Departures:
    text = unicodedata.normalize("NFKC", text or "")
    out = Departures()
    if not text.strip():
        return out
    if DAILY.search(text):
        out.frequency = "daily"
    weekdays = sorted({WEEKDAY_INDEX[w] for w in WEEKDAY.findall(text)})
    if weekdays and out.frequency == "unknown":
        out.frequency = "weekly"
        out.weekdays = weekdays
    found: list[date] = []
    consumed = text
    for year, month, day in FULL.findall(text):
        found.append(_valid(int(year), int(month), int(day)))
    consumed = FULL.sub(" ", consumed)
    ranged = RANGE.search(consumed)
    if ranged and not found:
        m1, d1, m2, d2 = ranged.groups()
        start = _year_for(int(m1), int(d1), reference)
        end = _year_for(int(m2 or m1), int(d2), start or reference)
        if start and end and end >= start:
            out.range = (start, end)
            out.frequency = "range" if out.frequency == "unknown" else out.frequency
        consumed = RANGE.sub(" ", consumed)
    for month, days in MONTH_DAYS.findall(consumed):
        for day in re.findall(r"\d{1,2}", days):
            found.append(_year_for(int(month), int(day), reference))
    consumed = MONTH_DAYS.sub(" ", consumed)
    for month, day in NUMERIC.findall(consumed):
        if 1 <= int(month) <= 12 and 1 <= int(day) <= 31:
            found.append(_year_for(int(month), int(day), reference))
    out.dates = sorted({d for d in found if d is not None})
    if out.dates and out.frequency == "unknown":
        out.frequency = "fixed"
    return out
