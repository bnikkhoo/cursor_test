"""pfa-intake CLI — contract for future CoS/FSP wiring."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from pfa_intake.audit import AuditLog
from pfa_intake.chase import chase_due_from_store
from pfa_intake.intake import decide_mail
from pfa_intake.legacy import import_legacy
from pfa_intake.paths import data_dir
from pfa_intake.schemas import WorkItemUpsert
from pfa_intake.store import WorkItemStore
from pfa_intake.views.frontdesk import FrontDeskView


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _load_json_arg(raw: str | None, file_path: str | None) -> dict[str, Any]:
    if file_path:
        return json.loads(Path(file_path).read_text(encoding="utf-8"))
    if raw:
        return json.loads(raw)
    raise SystemExit("provide --json or --file")


def cmd_upsert(args: argparse.Namespace) -> int:
    store = WorkItemStore(args.data)
    payload = _load_json_arg(args.json, args.file)
    item = store.upsert(WorkItemUpsert.model_validate(payload))
    _print(item.model_dump(mode="json"))
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    store = WorkItemStore(args.data)
    if args.key:
        item = store.get(args.key)
    else:
        item = store.get_by_person_doc(args.person, args.doc_class)
    if item is None:
        _print({"found": False})
        return 1
    _print(item.model_dump(mode="json"))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    store = WorkItemStore(args.data)
    items = store.list(open_only=args.open)
    _print([i.model_dump(mode="json") for i in items])
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    audit = AuditLog(args.data)
    result = audit.check(args.person, args.item)
    _print(result)
    return 0 if result["skip"] else 2


def cmd_complete(args: argparse.Namespace) -> int:
    audit = AuditLog(args.data)
    store = WorkItemStore(args.data)
    entry = audit.add(
        bot=args.bot,
        person=args.person,
        item=args.item,
        action=args.action,
        evidence=args.evidence or "",
        ref=args.ref,
    )
    # Optionally mark matching work item done
    if args.action in ("completed", "uploaded", "verified", "closed", "returned", "filed"):
        item = store.get_by_person_doc(args.person, args.item)
        if item is not None:
            store.mark_done(item.key)
    _print(entry.model_dump(mode="json"))
    return 0


def cmd_decide_mail(args: argparse.Namespace) -> int:
    payload = _load_json_arg(args.json, args.file)
    result = decide_mail(payload)
    _print(result.model_dump(mode="json"))
    return 0


def cmd_chase_due(args: argparse.Namespace) -> int:
    store = WorkItemStore(args.data)
    audit = AuditLog(args.data)
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    actions = chase_due_from_store(store, as_of=as_of, audit=audit)
    _print({"as_of": as_of.isoformat(), "actions": actions})
    return 0


def cmd_fd_queue(args: argparse.Namespace) -> int:
    view = FrontDeskView(args.data)
    rows = view.to_queue_jsonl_dicts(open_only=not args.all)
    _print(rows)
    return 0


def cmd_advance(args: argparse.Namespace) -> int:
    store = WorkItemStore(args.data)
    item = store.advance_stage(
        args.key,
        stage=args.stage,
        next_action=args.next_action,
        next_action_at=date.fromisoformat(args.next_action_at)
        if args.next_action_at
        else None,
        detail_note=args.notes,
    )
    # Refresh FD view so detail rewrites
    FrontDeskView(args.data).refresh()
    _print(item.model_dump(mode="json"))
    return 0


def cmd_import_legacy(args: argparse.Namespace) -> int:
    store = WorkItemStore(args.data)
    audit = AuditLog(args.data)
    result = import_legacy(
        store=store,
        audit=audit,
        tracker=Path(args.tracker) if args.tracker else None,
        queue=Path(args.queue) if args.queue else None,
        completions=Path(args.completions) if args.completions else None,
    )
    FrontDeskView(args.data).refresh()
    _print(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pfa-intake",
        description="PFA document intake engine (sidecar; does not touch live Grok bots)",
    )
    p.add_argument(
        "--data",
        default=None,
        help="Data directory (default: $PFA_INTAKE_DATA or ./data)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    up = sub.add_parser("upsert", help="Create or update a work item")
    up.add_argument("--json", default=None)
    up.add_argument("--file", default=None)
    up.set_defaults(func=cmd_upsert)

    get = sub.add_parser("get", help="Get a work item by key or person+doc_class")
    get.add_argument("--key", default=None)
    get.add_argument("--person", default=None)
    get.add_argument("--doc-class", default=None)
    get.set_defaults(func=cmd_get)

    ls = sub.add_parser("list", help="List work items")
    ls.add_argument("--open", action="store_true")
    ls.set_defaults(func=cmd_list)

    chk = sub.add_parser("check", help="Check completions log before chasing")
    chk.add_argument("--person", required=True)
    chk.add_argument("--item", required=True)
    chk.set_defaults(func=cmd_check)

    comp = sub.add_parser("complete", help="Append a completion audit line")
    comp.add_argument("--bot", required=True)
    comp.add_argument("--person", required=True)
    comp.add_argument("--item", required=True)
    comp.add_argument("--action", required=True)
    comp.add_argument("--evidence", default="")
    comp.add_argument("--ref", default=None)
    comp.set_defaults(func=cmd_complete)

    dm = sub.add_parser("decide-mail", help="Triage fly@ / WE / grokbot mail (no send)")
    dm.add_argument("--json", default=None)
    dm.add_argument("--file", default=None)
    dm.set_defaults(func=cmd_decide_mail)

    ch = sub.add_parser("chase-due", help="Compute due chase actions")
    ch.add_argument("--as-of", default=None, help="YYYY-MM-DD")
    ch.set_defaults(func=cmd_chase_due)

    fd = sub.add_parser("fd-queue", help="Derived Front Desk queue (detail refreshed)")
    fd.add_argument("--all", action="store_true", help="Include done rows")
    fd.set_defaults(func=cmd_fd_queue)

    adv = sub.add_parser("advance", help="Advance stage (rewrites FD detail)")
    adv.add_argument("--key", required=True)
    adv.add_argument("--stage", required=True)
    adv.add_argument("--next-action", default=None)
    adv.add_argument("--next-action-at", default=None)
    adv.add_argument("--notes", default=None)
    adv.set_defaults(func=cmd_advance)

    imp = sub.add_parser("import-legacy", help="Import fixture tracker/queue/completions")
    imp.add_argument("--tracker", default=None)
    imp.add_argument("--queue", default=None)
    imp.add_argument("--completions", default=None)
    imp.set_defaults(func=cmd_import_legacy)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.data:
        data_dir(args.data)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
