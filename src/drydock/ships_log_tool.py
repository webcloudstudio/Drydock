"""Repository-local Ship's Log agent utility."""

from __future__ import annotations

import argparse
from pathlib import Path

from drydock.ships_log import ShipsLogError, append_record, audit_log, create_record, ships_log_path


def repository_root() -> Path:
    """Return the Drydock source repository containing this module."""
    return Path(__file__).resolve().parents[2]


def _alternative(value: str) -> dict[str, str]:
    option, separator, reason = value.partition("::")
    if not separator or not option.strip() or not reason.strip():
        raise ShipsLogError("--alternative must use '<option>::<reason rejected>'.")
    return {"option": option.strip(), "reason_rejected": reason.strip()}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python bin/ships_log.py",
        description="Record or audit Drydock's repository-local Ship's Log.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    record = commands.add_parser("record", help="Append one material decision or milestone.")
    record.add_argument("--event-type", choices=["decision", "milestone"], required=True)
    record.add_argument("--title", required=True)
    record.add_argument("--summary", required=True)
    record.add_argument("--rationale", required=True)
    record.add_argument("--source-type", required=True)
    record.add_argument("--source-command")
    record.add_argument("--source-provider")
    record.add_argument("--scope", action="append", default=[])
    record.add_argument("--alternative", action="append", default=[])
    record.add_argument("--evidence", action="append", default=[])
    record.add_argument("--supersedes", action="append", default=[])
    record.add_argument("--tag", action="append", default=[])

    commands.add_parser("audit", help="Validate Drydock's canonical Ship's Log.")
    return parser


def main(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    """Run the repository-local utility against Drydock's canonical log."""
    args = _build_parser().parse_args(argv)
    target = root or repository_root()

    if args.command == "audit":
        result = audit_log(ships_log_path(target))
        print(f"Ship's Log: {result.path}")
        print(f"Records: {len(result.records)}")
        if result.findings:
            for finding in result.findings:
                print(f"  line {finding.line}: {finding.message}")
            print(f"RESULT: FAIL ({len(result.findings)} findings)")
            return 1
        print("RESULT: PASS")
        return 0

    record = create_record(
        event_type=args.event_type,
        title=args.title,
        summary=args.summary,
        rationale=args.rationale,
        source_type=args.source_type,
        source_command=args.source_command,
        source_provider=args.source_provider,
        affected_scope=args.scope,
        alternatives=[_alternative(value) for value in args.alternative],
        evidence=args.evidence,
        supersedes=args.supersedes,
        tags=args.tag,
    )
    path = append_record(target, record)
    print(f"Appended Ship's Log event {record['event_id']}")
    print(f"Saved to {path}")
    return 0
