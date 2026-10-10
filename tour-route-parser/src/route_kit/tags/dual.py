"""Dual-track rules: auxiliary rules the skill proposes, run beside the human-owned main rules.

An auxiliary rule is declarative: conditions over tag features, one target tag. It may only
assign a value that already exists in the vocabulary. On a single-valued key where main has
already set a value, main wins and the conflict is logged. A rule in ``shadow`` status is
evaluated and recorded under ``shadow`` but never written to the live tags.

Promotion copies a live rule into ``rules/promoted.yaml`` (human-owned, loaded with main) and
retires the auxiliary entry; rollback retires it. Both bump the auxiliary version; promotion
also bumps the promoted-rules version, which is part of the main version.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .library import DATA, Library, _load
from .models import DepartureTags, Evidence, RouteTags, Tag

PROMOTED = DATA / "rules" / "promoted.yaml"


def features(tags: RouteTags, departure: DepartureTags | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {f"route.{t.key}": t.value for t in tags.route}
    out["route.market"] = tags.market
    out["route.product_type"] = tags.product_type
    if departure is not None:
        out["departure.date"] = departure.date.isoformat()
        out["departure.month_day"] = departure.date.strftime("%m-%d")
        out["departure.weekday"] = departure.date.weekday()
        for t in departure.tags:
            out[f"departure.{t.key}"] = t.value
    return out


def _holds(condition: dict, feats: dict[str, Any]) -> bool:
    name, op, expected = condition.get("feature"), condition.get("op", "=="), condition.get("value")
    if name not in feats:
        return False
    actual = feats[name]
    if actual == "unknown":
        return False
    try:
        if op == "==":
            return actual == expected
        if op == "!=":
            return actual != expected
        if op == ">=":
            return actual >= expected
        if op == "<=":
            return actual <= expected
        if op == ">":
            return actual > expected
        if op == "<":
            return actual < expected
        if op == "in":
            return actual in expected
        if op == "contains":
            return isinstance(actual, list) and expected in actual
        if op == "between":
            lo, hi = expected
            return lo <= actual <= hi
    except TypeError:
        return False
    return False


def _outcomes(rule: dict, tags: RouteTags) -> list[tuple[DepartureTags | None, str, Any]]:
    target = rule.get("target") or {}
    key, value = target.get("key"), target.get("value")
    conditions = rule.get("when") or []
    if not key:
        return []
    if target.get("table") == "departure":
        return [
            (dep, key, value)
            for dep in tags.departures
            if all(_holds(c, features(tags, dep)) for c in conditions)
        ]
    feats = features(tags)
    return [(None, key, value)] if all(_holds(c, feats) for c in conditions) else []


def _vocab_allows(lib: Library, key: str, value: Any) -> bool:
    """An auxiliary rule may only assign words the vocabulary already has (or non-word values)."""
    if key not in lib.vocabulary.cardinality:
        return True
    return any(k == key and w.word == value for (k, _), w in lib.vocabulary.words.items())


def apply_aux(tags: RouteTags, lib: Library) -> None:
    aux_version = lib.rules.aux_version
    for rule in lib.rules.aux_rules:
        status = rule.get("status", "shadow")
        if status == "retired":
            continue
        rule_id = f"aux-{rule.get('id')}@{aux_version}"
        for dep, key, value in _outcomes(rule, tags):
            if not _vocab_allows(lib, key, value):
                tags.issues.append({"code": "AUX_VALUE_NOT_IN_VOCAB", "path": key, "detail": f"{rule.get('id')}: {value}"})
                continue
            holder = dep.tags if dep is not None else tags.route
            existing = next((t for t in holder if t.key == key), None)
            where = {"table": "departure", "date": dep.date.isoformat()} if dep is not None else {"table": "route"}
            if status == "shadow":
                tags.shadow.append({**where, "rule": rule_id, "key": key, "value": value,
                                    "main_value": existing.value if existing else None})
                continue
            if existing is None:
                holder.append(Tag(key=key, value=value, origin="aux", review="needs_review",
                                  evidence=Evidence(rule=rule_id)))
                continue
            if existing.cardinality == "multi" and isinstance(existing.value, list):
                if value not in existing.value:
                    existing.value = [*existing.value, value]
                    existing.note = (existing.note + "; " if existing.note else "") + f"{rule_id} 追加"
                    existing.review = "needs_review"
                continue
            if existing.value in ("unknown", None, []):
                existing.value = value
                existing.origin = "aux"
                existing.review = "needs_review"
                existing.evidence.rule = rule_id
                continue
            if existing.value != value:
                tags.conflicts.append({**where, "key": key, "main_value": existing.value, "aux_value": value,
                                       "aux_rule": rule_id, "main_rule": existing.evidence.rule})


# ---------------------------------------------------------------- shadow evaluation against gold


def load_gold(gold_dir: Path) -> dict[str, dict]:
    """``gold/<code>.gold.json``: {"code", "tags": {key: value}, "departures": {date: {key: value}}}."""
    gold: dict[str, dict] = {}
    if not gold_dir.exists():
        return gold
    for path in sorted(gold_dir.glob("*.gold.json")):
        data = json.loads(path.read_text())
        gold[data["code"]] = data
    return gold


def shadow_report(all_tags: list[RouteTags], gold: dict[str, dict]) -> dict[str, dict]:
    """Per shadow rule: how often its outcome agrees with the gold value where gold has one."""
    report: dict[str, dict] = {}
    for tags in all_tags:
        g = gold.get(tags.code)
        for row in tags.shadow:
            entry = report.setdefault(row["rule"], {"fired": 0, "compared": 0, "agree": 0, "conflicts_with_main": 0})
            entry["fired"] += 1
            if row.get("main_value") not in (None, "unknown", []) and row["main_value"] != row["value"]:
                entry["conflicts_with_main"] += 1
            if not g:
                continue
            if row["table"] == "route":
                expected = (g.get("tags") or {}).get(row["key"])
            else:
                expected = ((g.get("departures") or {}).get(row["date"]) or {}).get(row["key"])
            if expected is None:
                continue
            entry["compared"] += 1
            if (row["value"] in expected) if isinstance(expected, list) else (expected == row["value"]):
                entry["agree"] += 1
    for entry in report.values():
        entry["agreement"] = round(entry["agree"] / entry["compared"], 2) if entry["compared"] else None
    return report


# ---------------------------------------------------------------- promotion and rollback


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def _bump(data: dict) -> dict:
    data["version"] = int(data.get("version", 0)) + 1
    return data


def add_aux_rule(rule: dict, aux_path: Path = DATA / "rules" / "aux.yaml") -> None:
    data, _ = _load(aux_path)
    rules = data.get("rules") or []
    if any(r.get("id") == rule.get("id") for r in rules):
        raise ValueError(f"auxiliary rule {rule.get('id')} exists")
    rule = {**rule, "auxiliary": True, "status": rule.get("status", "shadow")}
    data["rules"] = [*rules, rule]
    _write_yaml(aux_path, _bump(data))


def set_status(rule_id: str, status: str, aux_path: Path = DATA / "rules" / "aux.yaml") -> None:
    data, _ = _load(aux_path)
    found = False
    for rule in data.get("rules") or []:
        if rule.get("id") == rule_id:
            rule["status"] = status
            found = True
    if not found:
        raise KeyError(rule_id)
    _write_yaml(aux_path, _bump(data))


def rollback(rule_id: str, aux_path: Path = DATA / "rules" / "aux.yaml") -> None:
    set_status(rule_id, "retired", aux_path)


def promote(rule_id: str, aux_path: Path = DATA / "rules" / "aux.yaml", promoted_path: Path = PROMOTED) -> None:
    data, _ = _load(aux_path)
    rule = next((r for r in data.get("rules") or [] if r.get("id") == rule_id), None)
    if rule is None:
        raise KeyError(rule_id)
    if rule.get("status") != "live":
        raise ValueError(f"only a live rule is promoted; {rule_id} is {rule.get('status')}")
    promoted = _load(promoted_path)[0] if promoted_path.exists() else {"version": 0, "rules": []}
    moved = {k: v for k, v in rule.items() if k not in ("auxiliary", "status")}
    moved["promoted_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    promoted["rules"] = [*(promoted.get("rules") or []), moved]
    _write_yaml(promoted_path, _bump(promoted))
    rule["status"] = "retired"
    rule["promoted"] = True
    _write_yaml(aux_path, _bump(data))
