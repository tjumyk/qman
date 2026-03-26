#!/usr/bin/env python3
"""Parse pasted ``ausearch`` stdout (raw default, or ``-i``) using ``app.docker_quota.audit_parser``.

Read full ausearch text from stdin or a file and print parsed events as JSON.

Run from the repo root with the ``qman`` conda env (or any env where the app
dependencies are installed) so ``import app`` succeeds:

  conda activate qman
  cat /tmp/ausearch.txt | python scripts/parse_ausearch_paste.py

  python scripts/parse_ausearch_paste.py -f /tmp/ausearch.txt

  python scripts/parse_ausearch_paste.py --summary < /tmp/ausearch.txt

With a bare ``python3`` on ``PYTHONPATH``, ensure Flask and other app deps are
installed, or use ``conda run -n qman python scripts/parse_ausearch_paste.py``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _read_input(path: str | None) -> str:
    if path:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    return sys.stdin.read()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse ausearch text (raw or -i) with audit_parser.parse_ausearch_stdout."
    )
    parser.add_argument(
        "-f",
        "--file",
        metavar="PATH",
        help="read ausearch output from this file instead of stdin",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="print event count and per-event one-line keys instead of full JSON",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="single-line JSON (ignored with --summary)",
    )
    args = parser.parse_args()

    logging.getLogger("app.docker_quota.audit_parser").setLevel(logging.WARNING)

    from app.docker_quota.audit_parser import parse_ausearch_stdout

    text = _read_input(args.file)
    events = parse_ausearch_stdout(text)

    if args.summary:
        print(f"events: {len(events)}")
        for i, ev in enumerate(events):
            parts = [
                f"#{i}",
                f"uid={ev.get('uid')}",
                f"auid={ev.get('auid')}",
                f"pid={ev.get('pid')}",
                f"key={ev.get('key')!r}",
                f"type={ev.get('type')!r}",
                f"ts={ev.get('timestamp') or ev.get('timestamp_unix')!r}",
                f"subcmd={ev.get('docker_subcommand')!r}",
                f"proctitle={ev.get('proctitle')!r}",
            ]
            print("  " + " ".join(parts))
        return 0

    indent = None if args.compact else 2
    print(json.dumps(events, indent=indent, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
