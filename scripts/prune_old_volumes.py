#!/usr/bin/env python3
"""Prune unused Docker volumes older than a given number of days.

Uses the Docker API (no CLI parsing). Run from project root with conda env 'qman' active,
or: python scripts/prune_old_volumes.py [--days 90] [--dry-run]
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone

import docker


def get_volumes_in_use(client: docker.DockerClient) -> set[str]:
    """Return set of volume names that are mounted by any container (running or stopped)."""
    in_use: set[str] = set()
    for container in client.containers.list(all=True):
        for mount in container.attrs.get("Mounts", []):
            name = mount.get("Name")
            if name:
                in_use.add(name)
    return in_use


def prune_old_volumes(days: int = 90, dry_run: bool = False) -> tuple[int, int, int]:
    """Prune unused volumes older than `days`. Returns (removed, skipped_in_use, skipped_new)."""
    client = docker.from_env()
    try:
        cutoff = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # Use a timedelta for exact day boundary
        cutoff = cutoff - timedelta(days=days)

        in_use = get_volumes_in_use(client)
        removed = 0
        skipped_in_use = 0
        skipped_new = 0

        for vol in client.volumes.list():
            name = vol.name
            if name in in_use:
                skipped_in_use += 1
                continue

            created_str = vol.attrs.get("CreatedAt")
            if not created_str:
                print(f"Warning: no CreatedAt for volume '{name}', skipping.", file=sys.stderr)
                continue

            # Docker returns e.g. "2024-11-01T12:34:56.123456789Z"
            try:
                created = datetime.fromisoformat(
                    created_str.replace("Z", "+00:00")
                )
            except ValueError:
                print(
                    f"Warning: could not parse CreatedAt for '{name}' ({created_str}), skipping.",
                    file=sys.stderr,
                )
                continue

            if created > cutoff:
                skipped_new += 1
                continue

            if dry_run:
                print(f"Would remove: {name} (created {created_str})")
                removed += 1
            else:
                try:
                    vol.remove()
                    print(f"Removed: {name} (created {created_str})")
                    removed += 1
                except docker.errors.APIError as e:
                    print(f"Error removing volume '{name}': {e}", file=sys.stderr)

        return removed, skipped_in_use, skipped_new
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prune unused Docker volumes older than N days."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        metavar="N",
        help="Remove only volumes created more than N days ago (default: 90)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List volumes that would be removed without removing them",
    )
    args = parser.parse_args()

    if args.days < 1:
        print("Error: --days must be >= 1", file=sys.stderr)
        return 1

    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=args.days)).date()
    print(f"Pruning unused volumes older than {args.days} days (cutoff: {cutoff_date}).")
    if args.dry_run:
        print("DRY RUN - no volumes will be removed.")
    print()

    try:
        removed, skipped_in_use, skipped_new = prune_old_volumes(
            days=args.days, dry_run=args.dry_run
        )
    except docker.errors.DockerException as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(
        f"\nDone. Removed: {removed}; "
        f"skipped (in use): {skipped_in_use}; "
        f"skipped (newer than {args.days}d): {skipped_new}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
