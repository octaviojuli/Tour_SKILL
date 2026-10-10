"""Review-side commands for the tag stage.

    python scripts/tags.py correct --out out --code UK6 --key hotel_tier --value '"豪华"' --reason rule_wrong
    python scripts/tags.py confirm --out out --code UK6 --key guide_language
    python scripts/tags.py fix-upstream --out out --code UK6 --key destinations --field 'days[].cities'
    python scripts/tags.py gold --out out              # gold files from confirmed/corrected routes
    python scripts/tags.py report --out out            # rebuild tags/report.md
    python scripts/tags.py aux list
    python scripts/tags.py aux add --out out           # queue every proposal in tags/report.json (shadow)
    python scripts/tags.py aux status <id> live|shadow|retired
    python scripts/tags.py aux promote <id>            # live -> main (rules/promoted.yaml)
    python scripts/tags.py aux rollback <id>

Corrections append to ``out/tags/corrections.jsonl``; rerun ``run.py --tag-only`` to apply them
to the records and pages. Any rule change marks routes stale; ``--tag-only`` re-tags them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from route_kit.tags import Correction, Library, RouteTags  # noqa: E402
from route_kit.tags import dual, review  # noqa: E402
from route_kit.tags.dual import load_gold  # noqa: E402


def corrections_path(out: Path) -> Path:
    (out / "tags").mkdir(parents=True, exist_ok=True)
    return out / "tags" / "corrections.jsonl"


def load_tags(out: Path, code: str) -> RouteTags:
    return RouteTags.model_validate_json((out / "routes" / f"{code}.tags.json").read_text())


def cmd_correction(args, action: str) -> None:
    tags = load_tags(args.out, args.code)
    old = tags.value(args.key, None)
    new = json.loads(args.value) if getattr(args, "value", None) is not None else None
    event = Correction(
        code=args.code, sha256=tags.sha256, key=args.key, old_value=old, new_value=new,
        action=action, reason=args.reason or ("parser_wrong" if action == "fix_upstream" else ""),
        parser_field=getattr(args, "field", "") or "", reviewer=args.reviewer, tagged_with=tags.tagged_with,
    )
    review.append_correction(corrections_path(args.out), event)
    print(f"{action}: {args.code} {args.key} {old!r} -> {new!r}")


def cmd_gold(args) -> None:
    """A route whose tags a person confirmed or corrected becomes a gold file."""
    gold_dir = args.out / "tags" / "gold"
    gold_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for path in sorted((args.out / "routes").glob("*.tags.json")):
        tags = RouteTags.model_validate_json(path.read_text())
        confirmed = {t.key: t.value for t in tags.route if t.review in ("confirmed", "corrected")}
        if not confirmed:
            continue
        departures = {
            d.date.isoformat(): {t.key: t.value for t in d.tags if t.review in ("confirmed", "corrected")}
            for d in tags.departures
        }
        data = {"code": tags.code, "sha256": tags.sha256, "tags": confirmed,
                "departures": {k: v for k, v in departures.items() if v}}
        (gold_dir / f"{tags.code}.gold.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
        written += 1
    print(f"gold: {written} routes with confirmed tags -> {gold_dir}")


def cmd_report(args) -> None:
    lib = Library()
    all_tags = [RouteTags.model_validate_json(p.read_text()) for p in sorted((args.out / "routes").glob("*.tags.json"))]
    corrections = review.load_corrections(corrections_path(args.out))
    report = review.batch_report(all_tags, corrections, lib, load_gold(args.out / "tags" / "gold"))
    (args.out / "tags" / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    (args.out / "tags" / "report.md").write_text(review.render_report(report))
    print(review.render_report(report))


def cmd_aux(args) -> None:
    lib = Library()
    if args.aux_cmd == "list":
        for rule in lib.rules.aux_rules:
            print(f"{rule.get('id')}\t{rule.get('status')}\t{rule.get('target')}\t{rule.get('when')}")
        for rule in lib.rules.promoted_rules:
            print(f"{rule.get('id')}\tpromoted\t{rule.get('target')}\t{rule.get('when')}")
        return
    if args.aux_cmd == "add":
        report_path = args.out / "tags" / "report.json"
        proposals = json.loads(report_path.read_text()).get("aux_proposals", [])
        for rule in proposals:
            dual.add_aux_rule(rule)
            print(f"queued (shadow): {rule['id']}")
        if not proposals:
            print("no proposals in the last report")
        return
    if args.aux_cmd == "status":
        dual.set_status(args.id, args.status)
    elif args.aux_cmd == "promote":
        dual.promote(args.id)
    elif args.aux_cmd == "rollback":
        dual.rollback(args.id)
    print(f"{args.aux_cmd}: {args.id} (aux version now {Library().rules.aux_version}; re-run run.py --tag-only)")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("correct", "confirm", "fix-upstream"):
        p = sub.add_parser(name)
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--code", required=True)
        p.add_argument("--key", required=True)
        p.add_argument("--reviewer", default="")
        p.add_argument("--reason", default="")
        if name == "correct":
            p.add_argument("--value", required=True, help="JSON value")
        if name == "fix-upstream":
            p.add_argument("--field", required=True, help="the parsed field at fault, e.g. days[].cities")
    for name in ("gold", "report"):
        sub.add_parser(name).add_argument("--out", type=Path, required=True)
    aux = sub.add_parser("aux")
    aux_sub = aux.add_subparsers(dest="aux_cmd", required=True)
    aux_sub.add_parser("list")
    aux_sub.add_parser("add").add_argument("--out", type=Path, required=True)
    status = aux_sub.add_parser("status")
    status.add_argument("id")
    status.add_argument("status", choices=["live", "shadow", "retired"])
    aux_sub.add_parser("promote").add_argument("id")
    aux_sub.add_parser("rollback").add_argument("id")
    args = parser.parse_args()
    if args.cmd in ("correct", "confirm", "fix-upstream"):
        cmd_correction(args, args.cmd.replace("-", "_"))
    elif args.cmd == "gold":
        cmd_gold(args)
    elif args.cmd == "report":
        cmd_report(args)
    else:
        cmd_aux(args)


if __name__ == "__main__":
    main()
