"""The `citenexus` console script. Currently one subcommand: `verify`."""

from __future__ import annotations

import sys

from citenexus.cli import verify as verify_cli


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] != "verify":
        print(
            "usage: citenexus verify <input.json> [--format text|json] [--question ...]",
            file=sys.stderr,
        )
        return 2
    return verify_cli.main(argv[1:])
