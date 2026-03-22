#!/usr/bin/env python3
"""Remove persisted ``docker exec`` rows from ``docker_usage_docker_event``.

These are ``container`` events whose Docker action starts with ``exec_`` (e.g.
``exec_create``, ``exec_start``, ``exec_die``). They are not used for attribution;
filtering was added in sync, but old rows may remain.

Run from the project root with the app on ``PYTHONPATH`` and ``DATABASE_URL`` set
if not using the default sqlite URL, e.g.:

  PYTHONPATH=. DATABASE_URL=sqlite:///path/to/qman.sqlite \\
    python scripts/cleanup_docker_exec_events.py

Or with conda env ``qman`` active from the repo root:

  PYTHONPATH=. python scripts/cleanup_docker_exec_events.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys

# Repo root on sys.path when executed as scripts/cleanup_docker_exec_events.py
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _exec_event_filter():
    """SQLAlchemy boolean expression: container-type docker events for exec lifecycle."""
    from sqlalchemy import and_, func

    from app.models_db import DockerUsageDockerEvent

    da = DockerUsageDockerEvent.docker_action
    return and_(
        func.lower(DockerUsageDockerEvent.docker_event_type) == "container",
        da.isnot(None),
        func.substr(func.lower(da), 1, 5) == "exec_",
    )


def count_exec_events() -> int:
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models_db import DockerUsageDockerEvent

    flt = _exec_event_filter()
    db = SessionLocal()
    try:
        n = db.scalar(select(func.count()).select_from(DockerUsageDockerEvent).where(flt))
        return int(n or 0)
    finally:
        db.close()


def delete_exec_events() -> int:
    from sqlalchemy import delete

    from app.db import SessionLocal
    from app.models_db import DockerUsageDockerEvent

    flt = _exec_event_filter()
    db = SessionLocal()
    try:
        res = db.execute(delete(DockerUsageDockerEvent).where(flt))
        db.commit()
        return int(res.rowcount or 0)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete docker_usage_docker_event rows for docker exec (exec_*) actions."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print how many rows would be deleted",
    )
    args = parser.parse_args()

    try:
        if args.dry_run:
            n = count_exec_events()
            print(f"Would delete {n} row(s) from docker_usage_docker_event (exec_* container events).")
            return 0
        n = delete_exec_events()
        print(f"Deleted {n} row(s) from docker_usage_docker_event.")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
