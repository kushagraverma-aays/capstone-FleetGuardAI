"""Operational CLI. Every command is idempotent and safe to re-run.

    python -m scripts.manage init-db            create schema, run migrations
    python -m scripts.manage seed [--if-empty]  generate the synthetic fleet
    python -m scripts.manage validate           check planted signal recovery
    python -m scripts.manage score [--if-empty] deploy rules and score the fleet
    python -m scripts.manage rebuild            init-db, seed, score, validate
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from sqlalchemy import func, select

from app.config import BACKEND_ROOT
from app.db import SessionLocal, ensure_database_exists
from app.logging_config import configure_logging, get_logger
from app.models import Prediction, Vehicle

log = get_logger("fleetguard.cli")


def _run(command: list[str]) -> int:
    log.info("running: %s", " ".join(command))
    return subprocess.call(command, cwd=BACKEND_ROOT)


def cmd_init_db(_args: argparse.Namespace) -> int:
    """Create the database if absent, then bring migrations to head."""
    ensure_database_exists()
    log.info("database present")
    return _run([sys.executable, "-m", "alembic", "upgrade", "head"])


def _vehicle_count() -> int:
    session = SessionLocal()
    try:
        return int(session.execute(select(func.count()).select_from(Vehicle)).scalar_one())
    finally:
        session.close()


def cmd_seed(args: argparse.Namespace) -> int:
    if args.if_empty and _vehicle_count() > 0:
        log.info("vehicles already present, skipping seed")
        return 0
    command = [sys.executable, "-m", "scripts.generate_data"]
    if args.seed is not None:
        command += ["--seed", str(args.seed)]
    if args.end_date:
        command += ["--end-date", args.end_date]
    return _run(command)


def cmd_validate(args: argparse.Namespace) -> int:
    command = [sys.executable, "-m", "scripts.validate_recovery"]
    if args.target is not None:
        command += ["--target", str(args.target)]
    return _run(command)


def _prediction_count() -> int:
    session = SessionLocal()
    try:
        return int(session.execute(select(func.count()).select_from(Prediction)).scalar_one())
    finally:
        session.close()


def cmd_score(args: argparse.Namespace) -> int:
    # --if-empty exists for container start-up: scoring the whole fleet takes
    # about a minute, and repeating it on every restart of an already-scored
    # database would delay the API coming up for no gain.
    if getattr(args, "if_empty", False) and _prediction_count() > 0:
        log.info("predictions already present, skipping scoring")
        return 0
    command = [sys.executable, "-m", "scripts.compute_predictions"]
    if args.redeploy_rules:
        command.append("--redeploy-rules")
    return _run(command)


def cmd_rebuild(args: argparse.Namespace) -> int:
    """The full pipeline, in the order the README documents."""
    steps = [
        ("init-db", lambda: cmd_init_db(args)),
        ("seed", lambda: cmd_seed(argparse.Namespace(if_empty=False, seed=None, end_date=None))),
        ("score", lambda: cmd_score(argparse.Namespace(redeploy_rules=True, if_empty=False))),
        ("validate", lambda: cmd_validate(argparse.Namespace(target=None))),
    ]
    for name, step in steps:
        log.info("rebuild step: %s", name)
        code = step()
        if code != 0:
            log.error("rebuild failed at step: %s", name)
            return code
    return 0


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="manage", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Create schema and run migrations.").set_defaults(
        handler=cmd_init_db
    )

    seed_parser = subparsers.add_parser("seed", help="Generate the synthetic fleet.")
    seed_parser.add_argument("--if-empty", action="store_true", help="Skip if data exists.")
    seed_parser.add_argument("--seed", type=int, default=None)
    seed_parser.add_argument("--end-date", type=str, default=None)
    seed_parser.set_defaults(handler=cmd_seed)

    validate_parser = subparsers.add_parser("validate", help="Check signal recovery.")
    validate_parser.add_argument("--target", type=float, default=None)
    validate_parser.set_defaults(handler=cmd_validate)

    score_parser = subparsers.add_parser("score", help="Deploy rules and score the fleet.")
    score_parser.add_argument("--redeploy-rules", action="store_true")
    score_parser.add_argument(
        "--if-empty", action="store_true", help="Skip if predictions already exist."
    )
    score_parser.set_defaults(handler=cmd_score)

    subparsers.add_parser(
        "rebuild", help="init-db, seed, score, validate - the whole pipeline."
    ).set_defaults(handler=cmd_rebuild)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
