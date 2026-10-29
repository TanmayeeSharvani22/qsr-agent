#!/usr/bin/env python3
"""Operator-taught learning CLI. The operator UI runs the same steps from the autonomy panel.

  setup      create/configure the `qsr-learner` Hermes profile (model endpoint, write approval on)
  import     append simulated or exported records to the unlearnt journal
  status     unlearnt record counts per service and event type
  run        have the learner model write learned-<service>; staged in Hermes for approval
  pending    list skill writes awaiting approval in the learner profile
  approve    apply a staged skill write with Hermes's /skills approve, then finalize
  reject     discard a staged skill write with Hermes's /skills reject, then finalize
  finalize   archive records of runs whose skill change was approved

Interactive alternative:  hermes -p qsr-learner  then  /skills pending  /skills diff <id>  /skills approve <id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autonomy.learning import Journal, learning_dir  # noqa: E402
from autonomy.learning_runner import (  # noqa: E402
    PROFILE, LearnerError, catalog_tools, counts_by_service, decide, finalize, pending_writes, run_service,
    setup_profile,
)


def cmd_setup(journal: Journal, _args: argparse.Namespace) -> int:
    print(setup_profile(journal))
    return 0


def cmd_import(journal: Journal, args: argparse.Namespace) -> int:
    for path in args.files:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        print(f"{path}: added {journal.append(records)} of {len(records)} records")
    return 0


def cmd_status(journal: Journal, args: argparse.Namespace) -> int:
    counts = counts_by_service(journal.records())
    print(f"Unlearnt operator responses: {sum(sum(c.values()) for c in counts.values())}  "
          f"(threshold {args.min_records} per event type)")
    for service, events in sorted(counts.items()):
        for event_type, count in sorted(events.items()):
            ready = "ready" if count >= args.min_records else "collecting"
            print(f"  {service:12} {event_type:28} {count:4}  {ready}")
    for run in journal.runs():
        if run.get("status") == "staged":
            print(f"Staged run {run['run_id']} for learned-{run['service']}: pending {run.get('pending_ids')}")
    return 0


def cmd_run(journal: Journal, args: argparse.Namespace) -> int:
    from autonomy.learning import learner_prompt
    from autonomy.worker import build_registry

    services = [args.service] if args.service else sorted(counts_by_service(journal.records()))
    tools = catalog_tools(build_registry(ROOT).catalog)
    ran = 0
    for service in services:
        if args.dry_run:
            records = [r for r in journal.records() if r["event"]["service"] == service]
            if records:
                path = journal.skill_path(service)
                print(learner_prompt(service, records, path.read_text() if path.is_file() else None, tools,
                                     min_support=args.min_support))
            continue
        try:
            run = run_service(journal, service, tools, args.min_records, args.min_support)
        except LearnerError as error:
            print(error)
            continue
        if run:
            print(run["content"])
            print(f"Run {run['run_id']} staged as pending skill write {run['pending_ids'][0]}.")
            print(f"Review: python scripts/learn.py approve {run['pending_ids'][0]}  (or reject), "
                  f"or interactively: hermes -p {PROFILE} -> /skills approve <id>")
            ran += 1
    if not ran and not args.dry_run:
        print("Nothing to learn: no service has enough unlearnt records.")
    return 0


def cmd_pending(_journal: Journal, _args: argparse.Namespace) -> int:
    records = pending_writes()
    if not records:
        print("No skill writes awaiting approval.")
    for record in records:
        print(f"{record.get('id')}  {record.get('action')}  {record.get('summary', '')}")
    return 0


def cmd_decide(journal: Journal, args: argparse.Namespace) -> int:
    try:
        result = decide(journal, args.pending_id, approve=args.command == "approve")
    except LearnerError as error:
        print(error)
        return 1
    print(result["message"])
    for run in result["runs"]:
        print(f"{run['run_id']}: {run['status']}")
    return 0


def cmd_finalize(journal: Journal, _args: argparse.Namespace) -> int:
    finalize(journal)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup")
    importer = sub.add_parser("import")
    importer.add_argument("files", nargs="+", type=Path)
    for name in ("status", "run"):
        command = sub.add_parser(name)
        command.add_argument("--min-records", type=int, default=5, help="unlearnt records per event type")
    runner = sub.choices["run"]
    runner.add_argument("--service", help="only this service")
    runner.add_argument("--min-support", type=int, default=2, help="consistent records per rule")
    runner.add_argument("--dry-run", action="store_true", help="print the learner prompt only")
    sub.add_parser("pending")
    for name in ("approve", "reject"):
        sub.add_parser(name).add_argument("pending_id")
    sub.add_parser("finalize")
    args = parser.parse_args()
    journal = Journal(learning_dir(ROOT))
    handlers = {"setup": cmd_setup, "import": cmd_import, "status": cmd_status, "run": cmd_run,
                "pending": cmd_pending, "approve": cmd_decide, "reject": cmd_decide, "finalize": cmd_finalize}
    return handlers[args.command](journal, args)


if __name__ == "__main__":
    raise SystemExit(main())
