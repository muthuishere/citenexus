"""The `citenexus` console script. Subcommands: `verify`, `cite-check`."""

from __future__ import annotations

import sys

from citenexus.cli import cite_check as cite_check_cli
from citenexus.cli import verify as verify_cli

_USAGE = (
    "usage:\n"
    "  citenexus verify <input.json> [--format text|json] [--question ...]\n"
    "  citenexus cite-check <claim> <evidence-dir> "
    "[--format text|json] [--min-coverage 0.0-1.0]"
)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(_USAGE, file=sys.stderr)
        return 2
    if argv[0] == "verify":
        return verify_cli.main(argv[1:])
    if argv[0] == "cite-check":
        return cite_check_cli.main(argv[1:])
    print(_USAGE, file=sys.stderr)
    return 2
