import argparse
import json
import sys
from collections.abc import Callable, Sequence
from typing import Any, TextIO

from vr_fares.client import search


def main(
    argv: Sequence[str] | None = None,
    *,
    search_fn: Callable[[str, str, str], dict[str, Any]] | None = None,
    stdout: TextIO | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="vr-fares")
    subparsers = parser.add_subparsers(dest="command", required=True)
    search_parser = subparsers.add_parser("search", help="search official VR Adult Fix fares")
    search_parser.add_argument("--from", dest="from_code", required=True)
    search_parser.add_argument("--to", dest="to_code", required=True)
    search_parser.add_argument("--date", required=True, help="travel date in YYYY-MM-DD format")
    args = parser.parse_args(argv)

    if args.command != "search":
        parser.error(f"unsupported command: {args.command}")

    result = (search_fn or search)(args.from_code, args.to_code, args.date)
    json.dump(result, stdout or sys.stdout, ensure_ascii=False, indent=2)
    (stdout or sys.stdout).write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
