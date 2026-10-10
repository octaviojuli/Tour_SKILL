"""Human review: correction events, applying them to tag records, and the batch report.

Corrections are appended to ``corrections.jsonl`` as structured events (see ``Correction``).
``parser_wrong`` / ``fix_upstream`` events are not counted against any rule: they go to the
parser issue list. Patterns in the remaining corrections become auxiliary-rule proposals.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .dual import features, shadow_report
from .library import Library
from .models import Correction, RouteTags


def append_correction(path: Path, correction: Correction) -> None:
    correction.at = correction.at or datetime.now(UTC).isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(correction.model_dump_json() + "\n")


def load_corrections(path: Path) -> list[Correction]:
    if not path.exists():
        return []
    return [Correction.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]


def apply_corrections(tags: RouteTags, corrections: list[Correction]) -> RouteTags:
    """The latest correction per (table, departure, key) wins; a confirm keeps the value."""
    latest: dict[tuple, Correction] = {}
    for c in corrections:
        if c.code != tags.code or (c.sha256 and tags.sha256 and c.sha256 != tags.sha256):
            continue
        latest[(c.table, c.departure, c.key)] = c
    for (table, departure, key), c in latest.items():
        if table == "route":
            holder = tags.route
        else:
            dep = next((d for d in tags.departures if d.date == departure), None)
            holder = dep.tags if dep else None
        if holder is None:
            continue
        tag = next((t for t in holder if t.key == key), None)
        if tag is None:
            continue
        if c.action == "confirm":
            tag.review = "confirmed"
        elif c.action == "correct":
            tag.value = c.new_value
            tag.review = "corrected"
            tag.note = (tag.note + "; " if tag.note else "") + f"人工修正({c.reason})"
        elif c.action == "fix_upstream":
            tag.review = "needs_review"
            tag.note = (tag.note + "; " if tag.note else "") + f"上游字段待修: {c.parser_field}"
    return tags


# ---------------------------------------------------------------- batch report


def _share_unknown(all_tags: list[RouteTags]) -> dict[str, float]:
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for tags in all_tags:
        for t in tags.route:
            counts[t.key][1] += 1
            if t.value in ("unknown", [], None):
                counts[t.key][0] += 1
    return {k: round(u / n, 2) for k, (u, n) in counts.items() if n}


def propose_aux_rules(
    all_tags: list[RouteTags], corrections: list[Correction], lib: Library
) -> list[dict]:
    """A (key, new_value) corrected on enough routes that share a feature becomes a proposal.

    Only route-table corrections with a rule-attributable reason count; the feature must hold on
    at least ``min_rate`` of the corrected routes and on at most ``max_background_rate`` of the
    other routes, so the proposal is specific, not a restatement of the whole batch.
    """
    rules = lib.rules
    min_cases = rules.get("aux_proposals", "min_cases", default=5)
    min_rate = rules.get("aux_proposals", "min_rate", default=0.6)
    max_bg = rules.get("aux_proposals", "max_background_rate", default=0.3)
    by_code = {t.code: t for t in all_tags}
    groups: dict[tuple[str, Any], set[str]] = defaultdict(set)
    for c in corrections:
        if c.action != "correct" or c.table != "route" or c.reason in ("parser_wrong", "source_ambiguous"):
            continue
        if c.code in by_code and c.new_value not in (None, "unknown"):
            groups[(c.key, json.dumps(c.new_value, ensure_ascii=False, sort_keys=True))].add(c.code)
    proposals = []
    existing_ids = {r.get("id") for r in rules.aux_rules}
    for (key, value_json), codes in groups.items():
        if len(codes) < min_cases:
            continue
        value = json.loads(value_json)
        corrected = [features(by_code[c]) for c in codes]
        others = [features(t) for t in all_tags if t.code not in codes]
        candidates: dict[tuple[str, str], int] = Counter()
        for feats in corrected:
            for name, val in feats.items():
                if name.startswith("route.") and name != f"route.{key}" and isinstance(val, (str, int, bool)) and val != "unknown":
                    candidates[(name, json.dumps(val, ensure_ascii=False))] += 1
        for (name, val_json), count in candidates.most_common(20):
            rate = count / len(corrected)
            if rate < min_rate:
                continue
            val = json.loads(val_json)
            background = sum(1 for f in others if f.get(name) == val) / len(others) if others else 0.0
            if background > max_bg:
                continue
            rule_id = f"aux-{key}-{abs(hash((name, val_json, value_json))) % 10**6}"
            if rule_id in existing_ids:
                continue
            proposals.append(
                {
                    "id": rule_id,
                    "auxiliary": True,
                    "status": "shadow",
                    "target": {"table": "route", "key": key, "value": value},
                    "when": [{"feature": name, "op": "==", "value": val}],
                    "origin": {"from": "corrections", "cases": len(codes), "rate": round(rate, 2),
                               "background_rate": round(background, 2),
                               "proposed_at": datetime.now(UTC).date().isoformat()},
                }
            )
            break  # one proposal per corrected (key, value): the most specific feature
    return proposals


def batch_report(
    all_tags: list[RouteTags], corrections: list[Correction], lib: Library, gold: dict[str, dict]
) -> dict:
    """Everything the evolution loop reads after a batch, as data; ``render_report`` makes it prose."""
    vocab_candidates: Counter = Counter()
    alias_candidates: Counter = Counter()
    for tags in all_tags:
        for p in tags.proposals:
            if p.kind == "vocab":
                vocab_candidates[(p.term, p.dimension, p.definition)] += p.frequency
            else:
                alias_candidates[(p.term, p.alias_kind)] += p.frequency
    rule_corrections: Counter = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    parser_issues: Counter = Counter()
    by_code = {t.code: t for t in all_tags}
    for c in corrections:
        if c.action == "fix_upstream" or c.reason == "parser_wrong":
            parser_issues[c.parser_field or c.key] += 1
            continue
        if c.action != "correct":
            continue
        tags = by_code.get(c.code)
        rule = ""
        if tags is not None:
            tag = tags.get(c.key) if c.table == "route" else None
            rule = tag.evidence.rule if tag else ""
        rule_corrections[rule or c.key] += 1
        if len(examples[rule or c.key]) < 3:
            examples[rule or c.key].append(f"{c.code}: {c.old_value} -> {c.new_value}")
    mismatches = [{"code": t.code, **m} for t in all_tags for m in t.issues if m["code"] == "PRODUCT_TYPE_MISMATCH"]
    conflicts = [{"code": t.code, **c} for t in all_tags for c in t.conflicts]
    return {
        "routes": len(all_tags),
        "stale": sum(1 for t in all_tags if t.stale),
        "needs_review": sum(1 for t in all_tags for x in t.route if x.review == "needs_review"),
        "vocab_candidates": [
            {"term": term, "dimension": dim, "definition": definition, "frequency": n}
            for (term, dim, definition), n in vocab_candidates.most_common(50)
        ],
        "alias_candidates": [
            {"term": term, "kind": kind, "frequency": n} for (term, kind), n in alias_candidates.most_common(100)
        ],
        "rule_corrections": [
            {"rule": rule, "corrections": n, "examples": examples[rule]} for rule, n in rule_corrections.most_common(30)
        ],
        "aux_proposals": propose_aux_rules(all_tags, corrections, lib),
        "shadow": shadow_report(all_tags, gold),
        "conflicts": conflicts[:100],
        "product_type_mismatches": mismatches,
        "parser_issues": [{"field": f, "count": n} for f, n in parser_issues.most_common(30)],
        "unknown_share": _share_unknown(all_tags),
        "versions": lib.versions(),
    }


def render_report(report: dict) -> str:
    lines = [
        "# 标签批次报告",
        "",
        f"线路 {report['routes']} 条，待审标签 {report['needs_review']} 个，版本过期 {report['stale']} 条。",
        "",
        "## 1. 新词候选（按频次）",
        "",
    ]
    lines += [f"- {c['term']}（{c['dimension']}，{c['frequency']} 次）{(' — ' + c['definition']) if c['definition'] else ''}" for c in report["vocab_candidates"]] or ["- 无"]
    lines += ["", "## 2. 别名候选", ""]
    lines += [f"- {c['term']}（{c['kind']}，{c['frequency']} 次）" for c in report["alias_candidates"]] or ["- 无"]
    lines += ["", "## 3. 规则修正统计（不含 parser_wrong）", ""]
    lines += [f"- {r['rule']}: {r['corrections']} 次修正；例：{'；'.join(r['examples'])}" for r in report["rule_corrections"]] or ["- 无"]
    lines += ["", "## 4. 辅助规则提案（进入 shadow）", ""]
    lines += [f"- {p['id']}: {p['target']} when {p['when']} ({p['origin']['cases']} 例，{p['origin']['rate']})" for p in report["aux_proposals"]] or ["- 无"]
    lines += ["", "## 5. Shadow 规则对照金标", ""]
    lines += [f"- {rule}: 触发 {s['fired']}，对照 {s['compared']}，一致率 {s['agreement']}，与主规则冲突 {s['conflicts_with_main']}" for rule, s in report["shadow"].items()] or ["- 无"]
    lines += ["", "## 6. 主/辅冲突（主规则生效）", ""]
    lines += [f"- {c['code']} {c['key']}: 主 {c['main_value']} / 辅 {c['aux_value']} ({c['aux_rule']})" for c in report["conflicts"]] or ["- 无"]
    lines += ["", "## 7. 产品类型：结构判断与登记不一致", ""]
    lines += [f"- {m['code']}: {m['detail']}" for m in report["product_type_mismatches"]] or ["- 无"]
    lines += ["", "## 8. 转给解析器的问题（fix upstream）", ""]
    lines += [f"- {p['field']}: {p['count']} 次" for p in report["parser_issues"]] or ["- 无"]
    lines += ["", "## 9. 各维度未标注占比", ""]
    lines += [f"- {k}: {v:.0%}" for k, v in sorted(report["unknown_share"].items(), key=lambda kv: -kv[1])]
    lines += ["", f"版本：{report['versions']}", ""]
    return "\n".join(lines)
